import datetime as dt

from rest_framework import serializers

from warehouse.models import Asm, Distributor, Pincode, Region, State, Target

from .models import MetricDefinition, ReconciliationRef

SCOPE_MODELS = {"region": Region, "state": State, "asm": Asm, "distributor": Distributor}


class MonthField(serializers.Field):
    """'YYYY-MM' <-> first-of-month date."""

    def to_representation(self, value):
        return value.strftime("%Y-%m") if value else None

    def to_internal_value(self, data):
        if isinstance(data, (dt.date, dt.datetime)):
            d = data.date() if isinstance(data, dt.datetime) else data
            return d.replace(day=1)
        s = str(data).strip()
        for fmt in ("%Y-%m", "%Y-%m-%d", "%b-%Y", "%b %Y", "%m/%Y"):
            try:
                return dt.datetime.strptime(s, fmt).date().replace(day=1)
            except ValueError:
                continue
        raise serializers.ValidationError("month must be YYYY-MM")


class TargetSerializer(serializers.ModelSerializer):
    month = MonthField()
    scope_name = serializers.SerializerMethodField()
    effective_from = serializers.DateField(required=False)

    class Meta:
        model = Target
        fields = ["id", "month", "scope_type", "scope_id", "scope_name", "metric", "value", "effective_from",
                  "notes", "version", "updated_by", "updated_at"]
        read_only_fields = ["version", "updated_by", "updated_at"]

    def get_scope_name(self, obj):
        if obj.scope_type == "overall":
            return "Overall"
        model = SCOPE_MODELS.get(obj.scope_type)
        o = model.objects.filter(pk=obj.scope_id).first() if model else None
        return o.name if o else None

    def validate(self, attrs):
        st = attrs.get("scope_type", getattr(self.instance, "scope_type", "overall"))
        sid = attrs.get("scope_id", getattr(self.instance, "scope_id", None))
        if st == "overall":
            attrs["scope_id"] = None
        else:
            if sid is None:
                raise serializers.ValidationError({"scope_id": f"required for scope_type '{st}'"})
            if not SCOPE_MODELS[st].objects.filter(pk=sid).exists():
                raise serializers.ValidationError({"scope_id": f"unknown {st} id {sid}"})
        if "value" in attrs and attrs["value"] < 0:
            raise serializers.ValidationError({"value": "must be >= 0"})
        if not self.instance and not attrs.get("effective_from"):
            attrs["effective_from"] = dt.date.today()
        return attrs


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ["id", "code", "name"]


def _fk(model, source, required=False):
    return serializers.PrimaryKeyRelatedField(source=source, queryset=model.objects.all(), allow_null=not required,
                                              required=required)


class StateSerializer(serializers.ModelSerializer):
    region_id = _fk(Region, "region")
    region_name = serializers.CharField(source="region.name", read_only=True, default=None)

    class Meta:
        model = State
        fields = ["id", "code", "name", "region_id", "region_name"]


class AsmSerializer(serializers.ModelSerializer):
    region_id = _fk(Region, "region")
    region_name = serializers.CharField(source="region.name", read_only=True, default=None)

    class Meta:
        model = Asm
        fields = ["id", "code", "name", "email", "phone", "region_id", "region_name", "is_active"]


class PincodeSerializer(serializers.ModelSerializer):
    state_id = _fk(State, "state", required=True)
    state_name = serializers.CharField(source="state.name", read_only=True, default=None)
    asm_id = _fk(Asm, "asm")
    asm_name = serializers.CharField(source="asm.name", read_only=True, default=None)
    distributor_p1_id = _fk(Distributor, "distributor_p1")
    distributor_p1_name = serializers.CharField(source="distributor_p1.name", read_only=True, default=None)
    distributor_p2_id = _fk(Distributor, "distributor_p2")
    distributor_p2_name = serializers.CharField(source="distributor_p2.name", read_only=True, default=None)

    class Meta:
        model = Pincode
        fields = ["id", "pincode", "district", "city", "state_id", "state_name", "asm_id", "asm_name",
                  "distributor_p1_id", "distributor_p1_name", "distributor_p2_id", "distributor_p2_name",
                  "is_serviceable"]

    def validate_pincode(self, v):
        v = str(v).strip()
        if len(v) != 6 or not v.isdigit() or v[0] == "0":
            raise serializers.ValidationError("pincode must be 6 digits and not start with 0")
        return v


class ReconciliationSerializer(serializers.ModelSerializer):
    """`period` is the month as YYYY-MM (`month` accepted as an alias on write)."""

    period = MonthField(source="month")

    class Meta:
        model = ReconciliationRef
        fields = ["id", "metric", "period", "mis_value", "tolerance_pct", "notes", "updated_by", "updated_at"]
        read_only_fields = ["updated_by", "updated_at"]

    def to_internal_value(self, data):
        if hasattr(data, "get") and "period" not in data and "month" in data:
            data = dict(data.items())
            data["period"] = data.pop("month")
        return super().to_internal_value(data)


class MetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricDefinition
        fields = ["code", "name", "definition", "formula", "source", "owner", "refresh", "updated_at"]
        read_only_fields = ["updated_at"]
