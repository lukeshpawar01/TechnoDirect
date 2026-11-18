from .channel_konnect import ChannelKonnectConnector
from .google_sheets import GoogleSheetsConnector
from .supabase import SupabaseConnector
from .payu import PayUConnector

# Order matters: refresh_all runs them in this sequence.
CONNECTORS = {
    "supabase": SupabaseConnector,
    "payu": PayUConnector,
    "google_sheets": GoogleSheetsConnector,
    "channel_konnect": ChannelKonnectConnector,
}


def get_connector(source):
    try:
        return CONNECTORS[source]()
    except KeyError:
        raise ValueError(f"Unknown source '{source}'. Valid: {sorted(CONNECTORS)}") from None
