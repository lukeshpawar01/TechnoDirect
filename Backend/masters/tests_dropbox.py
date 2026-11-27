"""BlueOrigin from Dropbox (masters/dropbox_bo.py) against a fake Dropbox: only BlueOrigin files, only changed ones,
deletions follow, failures are reported without secrets and keep the previous import."""
import json
import os
import tempfile
from unittest import mock

from django.test import TestCase, override_settings

from masters import dropbox_bo

CREDS = dict(DROPBOX_APP_KEY="k", DROPBOX_APP_SECRET="s3cret-value", DROPBOX_REFRESH_TOKEN="rt-value",
             DROPBOX_BO_PATH="/Power BI", DROPBOX_BO_MIRROR="")


class Resp:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code, self._body, self._content = status, body, content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body

    def iter_content(self, _n):
        yield self._content


class FakeDropbox:
    def __init__(self, files):
        self.files = dict(files)  # name -> (hash, bytes)
        self.downloads, self.token_status = [], 200
        self.scope = "account_info.read files.content.read files.metadata.read"

    def post(self, url, **kw):
        if url == dropbox_bo.TOKEN_URL:
            if self.token_status != 200:
                return Resp(self.token_status, {"error": "invalid_grant", "error_description": "refresh token is malformed"})
            return Resp(200, {"access_token": "at", "scope": self.scope})
        if url.endswith("/files/list_folder"):
            assert kw["json"]["path"] == "/Power BI"
            entries = [{".tag": "file", "name": n, "id": f"id:{n}", "content_hash": h} for n, (h, _b) in self.files.items()]
            entries.append({".tag": "folder", "name": "BO_Dashboard", "id": "id:dir"})
            return Resp(200, {"entries": entries, "has_more": False, "cursor": "c"})
        if url.endswith("/files/download"):
            name = json.loads(kw["headers"]["Dropbox-API-Arg"])["path"][3:]
            self.downloads.append(name)
            return Resp(200, content=self.files[name][1])
        raise AssertionError(url)


@override_settings(**CREDS)
class DropboxMirrorTests(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.dbx = FakeDropbox({"FY27_qtr2.csv": ("h1", b"a,b\n"), "FY27_qtr1.csv": ("h2", b"c\n"),
                                "Dist-state.xlsx": ("h3", b"x"), "Monthwise.csv": ("h4", b"big"),
                                "bo-data-service-account.json": ("h5", b"{}")})

    def test_only_changed_blueorigin_files_are_downloaded(self):
        m = dropbox_bo.mirror(self.dir, session=self.dbx)
        self.assertEqual(sorted(m["downloaded"]), ["Dist-state.xlsx", "FY27_qtr1.csv", "FY27_qtr2.csv"])
        self.assertEqual(open(os.path.join(self.dir, "FY27_qtr2.csv"), "rb").read(), b"a,b\n")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "Monthwise.csv")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "bo-data-service-account.json")))
        self.dbx.downloads.clear()
        self.assertEqual(dropbox_bo.mirror(self.dir, session=self.dbx)["downloaded"], [])  # nothing changed
        self.dbx.files["FY27_qtr2.csv"] = ("h9", b"new\n")
        del self.dbx.files["FY27_qtr1.csv"]
        m = dropbox_bo.mirror(self.dir, session=self.dbx)
        self.assertEqual((m["downloaded"], m["removed"]), (["FY27_qtr2.csv"], ["FY27_qtr1.csv"]))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "FY27_qtr1.csv")))
        self.assertFalse([f for f in os.listdir(self.dir) if f.startswith(".part-")])

    def test_compact_dashboard_file_replaces_the_quarter_files(self):
        dropbox_bo.mirror(self.dir, session=self.dbx)  # before the notebook writes the compact file: quarter files
        self.assertTrue(os.path.exists(os.path.join(self.dir, "FY27_qtr2.csv")))
        self.dbx.files["TD_BO_dashboard.csv.gz"] = ("h6", b"gz")
        self.dbx.downloads.clear()
        m = dropbox_bo.mirror(self.dir, session=self.dbx)
        self.assertEqual(m["downloaded"], ["TD_BO_dashboard.csv.gz"])  # only the one small file
        self.assertEqual(sorted(m["removed"]), ["FY27_qtr1.csv", "FY27_qtr2.csv"])  # local quarter copies freed
        self.assertEqual(sorted(f for f in os.listdir(self.dir) if not f.startswith(".")),
                         ["Dist-state.xlsx", "TD_BO_dashboard.csv.gz"])

    def test_bad_credentials_explain_without_secrets(self):
        self.dbx.token_status = 400
        with self.assertRaises(dropbox_bo.DropboxError) as cm:
            dropbox_bo.mirror(self.dir, session=self.dbx)
        msg = str(cm.exception)
        self.assertIn("dropbox_auth", msg)
        for secret in ("s3cret-value", "rt-value"):
            self.assertNotIn(secret, msg)

    def test_token_without_read_permissions_says_how_to_fix(self):
        self.dbx.scope = "account_info.read"
        with self.assertRaises(dropbox_bo.DropboxError) as cm:
            dropbox_bo.mirror(self.dir, session=self.dbx)
        self.assertIn("files.metadata.read", str(cm.exception))
        self.assertIn("Submit", str(cm.exception))
        self.assertEqual(self.dbx.downloads, [])

    def test_auth_link_asks_for_the_scopes_and_a_bad_code_is_not_saved(self):
        import io

        from django.core.management import call_command
        from django.core.management.base import CommandError

        out = io.StringIO()
        call_command("dropbox_auth", stdout=out)
        self.assertIn("scope=files.metadata.read+files.content.read", out.getvalue())
        resp = Resp(200, {"refresh_token": "new-rt", "scope": "account_info.read"})
        with mock.patch("masters.management.commands.dropbox_auth.requests.post", return_value=resp), \
                mock.patch("masters.management.commands.dropbox_auth.save_env") as save:
            with self.assertRaisesRegex(CommandError, "files.metadata.read"):
                call_command("dropbox_auth", code="abc")
        save.assert_not_called()

    def test_folder_without_sheets_is_an_error(self):
        self.dbx.files = {"Monthwise.csv": ("h", b"")}
        with self.assertRaisesRegex(dropbox_bo.DropboxError, "DROPBOX_BO_PATH"):
            dropbox_bo.mirror(self.dir, session=self.dbx)

    def test_refresh_reports_a_dropbox_failure_and_keeps_the_old_import(self):
        from ingestion.models import SyncRun
        from masters.blueorigin import refresh_if_changed

        with mock.patch.object(dropbox_bo, "mirror", side_effect=dropbox_bo.DropboxError("Dropbox sign-in failed (401)")), \
                mock.patch("masters.blueorigin.import_folder") as imp:
            step = refresh_if_changed()
        self.assertEqual(step["status"], "failed")
        imp.assert_not_called()
        self.assertIn("sign-in failed", SyncRun.objects.get(pk=step["run_id"]).error)

    @override_settings(DROPBOX_REFRESH_TOKEN="")
    def test_not_configured_falls_back_to_the_folder(self):
        self.assertFalse(dropbox_bo.configured())

    def test_save_env_replaces_the_placeholder(self):
        from masters.management.commands.dropbox_auth import save_env

        p = os.path.join(self.dir, ".env")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("A=1\nDROPBOX_REFRESH_TOKEN=REPLACE_ME_x\nB=2\n")
        save_env("DROPBOX_REFRESH_TOKEN", "tok", p)
        save_env("NEW_KEY", "v", p)
        self.assertEqual(open(p, encoding="utf-8").read(), "A=1\nDROPBOX_REFRESH_TOKEN=tok\nB=2\nNEW_KEY=v\n")
