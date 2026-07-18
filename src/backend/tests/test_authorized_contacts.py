"""Sprint 18: smoke tests for authorized_contacts store and resolution logic.

Run inside the backend container:
    cd /app && python -m unittest src.tests.test_authorized_contacts -v
"""

import json
import tempfile
import unittest
from pathlib import Path


class AuthorizedContactsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Patch the module paths to point at tmp
        from src.services import smtp_service as svc
        self.svc = svc
        self._orig_contacts_path = svc._AUTHORIZED_CONTACTS_PATH
        self._orig_emails_path = svc._AUTHORIZED_EMAILS_PATH
        svc._AUTHORIZED_CONTACTS_PATH = self.root / "authorized_contacts.json"
        svc._AUTHORIZED_EMAILS_PATH = self.root / "authorized_emails.json"

    def tearDown(self):
        self.svc._AUTHORIZED_CONTACTS_PATH = self._orig_contacts_path
        self.svc._AUTHORIZED_EMAILS_PATH = self._orig_emails_path
        self.tmp.cleanup()

    def _save(self, store):
        self.svc.save_authorized_contacts(store)

    def test_empty_store(self):
        self.assertFalse(self.svc.is_email_authorized("a@b.c"))
        self.assertFalse(self.svc.is_email_authorized("a@b.c", "fid1"))

    def test_global_only(self):
        self._save({
            "global": [{"email": "a@b.c"}, {"email": "x@y.z"}],
            "per_frontend": {},
        })
        self.assertTrue(self.svc.is_email_authorized("a@b.c"))
        self.assertTrue(self.svc.is_email_authorized("A@B.C"))  # case-insensitive
        self.assertTrue(self.svc.is_email_authorized(" x@y.z "))  # trim
        self.assertFalse(self.svc.is_email_authorized("missing@x.y"))
        # Without frontend_id and with unknown fid, resolves to global
        self.assertTrue(self.svc.is_email_authorized("a@b.c", "unknown-fid"))

    def test_mode_replace(self):
        self._save({
            "global": [{"email": "global@x.y"}],
            "per_frontend": {
                "fid1": {"mode": "replace", "contacts": [{"email": "only@fid1.com"}]},
            },
        })
        # Global email must NOT be authorized on the replace frontend
        self.assertFalse(self.svc.is_email_authorized("global@x.y", "fid1"))
        self.assertTrue(self.svc.is_email_authorized("only@fid1.com", "fid1"))
        # Global email still authorized globally or on frontends without override
        self.assertTrue(self.svc.is_email_authorized("global@x.y"))
        self.assertTrue(self.svc.is_email_authorized("global@x.y", "other-fid"))

    def test_mode_append(self):
        self._save({
            "global": [{"email": "global@x.y"}],
            "per_frontend": {
                "fid1": {"mode": "append", "contacts": [{"email": "extra@fid1.com"}]},
            },
        })
        # Append: both global and per-frontend emails authorized
        self.assertTrue(self.svc.is_email_authorized("global@x.y", "fid1"))
        self.assertTrue(self.svc.is_email_authorized("extra@fid1.com", "fid1"))
        # Per-frontend-only email NOT authorized on a different frontend
        self.assertFalse(self.svc.is_email_authorized("extra@fid1.com", "other-fid"))

    def test_invalid_email_rejected(self):
        # _normalise_contact drops entries without "@"
        self._save({
            "global": [{"email": "notanemail"}, {"email": "ok@x.y"}],
            "per_frontend": {},
        })
        self.assertFalse(self.svc.is_email_authorized("notanemail"))
        self.assertTrue(self.svc.is_email_authorized("ok@x.y"))

    def test_migration_from_legacy_emails(self):
        # Write legacy authorized_emails.json, no authorized_contacts.json
        legacy = self.root / "authorized_emails.json"
        legacy.write_text(json.dumps({"emails": ["one@x.y", "Two@X.Y", "  "]}))
        self.assertTrue(legacy.exists())
        # Trigger migration via a load call
        store = self.svc.load_authorized_contacts()
        self.assertEqual(len(store["global"]), 2)
        emails = {c["email"] for c in store["global"]}
        self.assertEqual(emails, {"one@x.y", "two@x.y"})
        # Legacy file renamed to .bak
        self.assertFalse(legacy.exists())
        self.assertTrue((self.root / "authorized_emails.json.bak").exists())

    def test_backward_compat_load_save(self):
        # save_authorized_emails must preserve the global list semantics
        self.svc.save_authorized_emails(["a@b.c", "x@y.z"])
        self.assertEqual(self.svc.load_authorized_emails(), ["a@b.c", "x@y.z"])
        self.assertTrue(self.svc.is_email_authorized("a@b.c"))

    def test_save_roundtrip_normalises(self):
        clean = self.svc.save_authorized_contacts({
            "global": [
                {"email": "A@B.C", "first_name": "Alice"},
                {"email": "a@b.c"},  # duplicate after lowercasing → dropped
                {"email": "bad"},  # invalid
                {"not_a_dict": True},
            ],
            "per_frontend": {
                "fid1": {
                    "mode": "invalid-mode",  # falls back to replace
                    "contacts": [{"email": "x@y.z"}],
                },
            },
        })
        self.assertEqual(len(clean["global"]), 1)
        self.assertEqual(clean["global"][0]["email"], "a@b.c")
        self.assertEqual(clean["global"][0]["first_name"], "Alice")
        self.assertEqual(clean["per_frontend"]["fid1"]["mode"], "replace")


if __name__ == "__main__":
    unittest.main()
