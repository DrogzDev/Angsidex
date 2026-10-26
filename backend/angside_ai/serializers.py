import re

from rest_framework import serializers

from leads.models import Lead

PHONE_RE = re.compile(r'^\+?[0-9][0-9 ()\-]{5,24}$')


def _clean(value: str) -> str:
    return ' '.join(value.split())


class SessionCreateSerializer(serializers.Serializer):
    # Obligatorios
    name = serializers.CharField(min_length=2, max_length=120)
    business = serializers.CharField(min_length=2, max_length=160)
    email = serializers.EmailField(required=False, allow_blank=True, max_length=254)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=32)
    sector = serializers.CharField(min_length=2, max_length=120)
    need = serializers.CharField(min_length=10, max_length=1500)
    # Opcionales
    whatsapp = serializers.CharField(required=False, allow_blank=True, max_length=32)
    location = serializers.CharField(required=False, allow_blank=True, max_length=120)
    has_website = serializers.ChoiceField(choices=Lead.HasWebsite.choices, required=False, allow_blank=True)
    budget_range = serializers.ChoiceField(choices=Lead.Budget.choices, required=False, allow_blank=True)
    start_when = serializers.ChoiceField(choices=Lead.StartWhen.choices, required=False, allow_blank=True)
    # Consentimiento comercial: independiente, opcional y falso por defecto.
    marketing_consent = serializers.BooleanField(required=False, default=False)
    turnstile_token = serializers.CharField(max_length=2048)
    # Campo trampa: las personas no lo ven; los bots suelen llenarlo.
    website_url = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate_name(self, v): return _clean(v)
    def validate_business(self, v): return _clean(v)
    def validate_sector(self, v): return _clean(v)
    def validate_need(self, v): return _clean(v)
    def validate_location(self, v): return _clean(v)

    def validate_phone(self, v):
        v = v.strip()
        if v and not PHONE_RE.match(v):
            raise serializers.ValidationError('Teléfono inválido.')
        return v

    def validate_whatsapp(self, v):
        v = v.strip()
        if v and not PHONE_RE.match(v):
            raise serializers.ValidationError('WhatsApp inválido.')
        return v

    def validate(self, attrs):
        if not attrs.get('email') and not attrs.get('phone'):
            raise serializers.ValidationError({'email': 'Indica un correo o un teléfono de contacto.'})
        return attrs


class MessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=5000, trim_whitespace=True)


class ContactRequestSerializer(serializers.Serializer):
    message = serializers.CharField(required=False, allow_blank=True, max_length=500)
    proposal_id = serializers.IntegerField(required=False, min_value=1)


class ProfileUpdateSerializer(serializers.Serializer):
    business_size = serializers.ChoiceField(choices=Lead.BusinessSize.choices)
