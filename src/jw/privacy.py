"""Shared fail-closed disclosure policy. Consent never changes sensitivity."""

from .contracts import canonical, digest, image_markup, instant, require, string, utcnow

PREPARATION = {"preparation:model", "preparation:local", "preparation:export"}
EXCEPTIONS = {"ats:manual", "referral:manual"}
SCOPES = PREPARATION | EXCEPTIONS


def decision(source, claim, scopes, purpose, channel, consent=False, media="text"):
    """Pure evaluator shared by preparation and explicitly scoped previews."""
    if media != "text" or image_markup(source["text"]):
        return "image_unclassified"
    if source["state"] != "active" or claim["state"] != "active":
        return "inactive"
    scope = purpose + ":" + channel
    if scope not in SCOPES or scope not in scopes:
        return "scope_denied"
    restricted = source["sensitivity"] != "public" or claim["sensitivity"] != "public"
    if scope in PREPARATION:
        return "sensitivity_denied" if restricted else "allowed"
    return "allowed" if consent is True else "application_consent_required"


class Privacy:
    def __init__(self, workspace):
        self.ws = workspace
        self.db = workspace.db

    def scopes(self, claim_id):
        row = self.db.execute("SELECT scopes FROM disclosure_rules WHERE claim_id=?", (claim_id,)).fetchone()
        import json
        return set(json.loads(row[0])) if row else set(PREPARATION)

    def preparation_allowed(self, source, claim):
        # One conservative envelope prevents a field from leaking through an
        # alternate preparation output. Removing any route removes it from all.
        scopes = self.scopes(claim["id"])
        return all(decision(source, claim, scopes, "preparation", channel) == "allowed"
                   for channel in ("model", "local", "export"))

    def set_rule(self, claim_id, scopes):
        require(isinstance(scopes, list) and len(scopes) <= len(SCOPES)
                and all(isinstance(s, str) and s in SCOPES for s in scopes)
                and len(scopes) == len(set(scopes)), "invalid_schema", "Provide unique supported disclosure scopes.")
        with self.ws.store.transaction():
            self.ws.store.one("claims", claim_id)
            self.db.execute("INSERT INTO disclosure_rules VALUES (?,?) ON CONFLICT(claim_id) "
                            "DO UPDATE SET scopes=excluded.scopes", (claim_id, canonical(sorted(scopes))))
            self.db.execute("UPDATE disclosure_consents SET revoked=1 WHERE claim_id=?", (claim_id,))
            self.ws.store.audit("disclosure_rule_changed", claim_id)
        return {"claim_id": claim_id, "scopes": sorted(scopes), "consents_revoked": True}

    def binding(self, claim, source, job_id, purpose, recipient):
        return digest({"claim": dict(claim), "source_sha": source["sha256"],
                       "source_state": source["state"], "source_sensitivity": source["sensitivity"],
                       "scopes": sorted(self.scopes(claim["id"])), "job_id": job_id,
                       "purpose": purpose, "recipient": recipient})

    def grant(self, claim_id, job_id, purpose, recipient, expires_at, confirm):
        from .workspace import identifier
        require(confirm is True, "consent_required", "Explicit per-application consent is required.")
        require(isinstance(purpose, str) and purpose + ":manual" in EXCEPTIONS,
                "policy_denied", "Exceptions are limited to manual ATS/referral previews.")
        string(recipient, 254)
        expiry = instant(expires_at)
        require(instant(utcnow()) < expiry, "consent_expired", "Consent must expire in the future.")
        with self.ws.store.transaction():
            self.ws.store.one("jobs", job_id)
            claim = self.ws.store.one("claims", claim_id)
            source = self.ws.store.one("sources", claim["source_id"])
            require(decision(source, claim, self.scopes(claim_id), purpose, "manual", True) == "allowed",
                    "policy_denied", "Field policy does not allow this disclosure.")
            consent_id = identifier("cns")
            self.db.execute("INSERT INTO disclosure_consents VALUES (?,?,?,?,?,?,?,0)",
                            (consent_id, claim_id, job_id, purpose, recipient, expiry.isoformat(),
                             self.binding(claim, source, job_id, purpose, recipient)))
            self.ws.store.audit("disclosure_consent_granted", consent_id)
        return {"consent_id": consent_id, "expires_at": expiry.isoformat(), "external_action": False}

    def revoke(self, consent_id):
        string(consent_id, 100)
        with self.ws.store.transaction():
            require(self.db.execute("SELECT 1 FROM disclosure_consents WHERE id=?", (consent_id,)).fetchone(),
                    "not_found", "Consent not found.")
            self.db.execute("UPDATE disclosure_consents SET revoked=1 WHERE id=?", (consent_id,))
            self.ws.store.audit("disclosure_consent_revoked", consent_id)
        return {"revoked": True}

    def preview(self, claim_id, job_id, purpose, recipient, consent_id=None, media="text"):
        string(purpose, 40)
        string(recipient, 254)
        require(media in ("text", "image"), "invalid_schema", "Unsupported media type.")
        if consent_id is not None:
            string(consent_id, 100)
        with self.ws.store.transaction():
            self.ws.store.one("jobs", job_id)
            claim = self.ws.store.one("claims", claim_id)
            source = self.ws.store.one("sources", claim["source_id"])
            consent = self.db.execute("SELECT * FROM disclosure_consents WHERE id=?", (consent_id,)).fetchone()
            authorized = bool(consent and not consent["revoked"]
                and consent["claim_id"] == claim_id and consent["job_id"] == job_id
                and consent["purpose"] == purpose and consent["recipient"] == recipient
                and instant(utcnow()) < instant(consent["expires_at"])
                and consent["binding"] == self.binding(claim, source, job_id, purpose, recipient))
            reason = decision(source, claim, self.scopes(claim_id), purpose, "manual", authorized, media)
            self.ws.store.audit("disclosure_allowed" if reason == "allowed" else "disclosure_denied", claim_id)
            result = {"allowed": reason == "allowed", "reason": reason, "external_action": False,
                      "ready": False, "media": media}
            if result["allowed"]:
                result["text"] = claim["text"]
                result["warning"] = "Explicit manual disclosure preview; exported copies cannot be recalled."
            return result
