"""Unit tests for P2-4 Track D curated skill lifecycle primitives.

Covers the pure functions that underpin the HTTP lifecycle endpoints:

- ``next_semver`` semver bump arithmetic (first approval reserves 0.1.0;
  major from None still returns 0.1.0; invalid prior semver rejects).
- ``revision_hash_of`` is stable against ``_VOLATILE_FIELDS`` (so editing
  a pending submission's ``submission_note`` / ``parent_curated_id``
  does not change the content hash used for cross-version dedup).
"""

from __future__ import annotations

import pytest

from src.application.services.skill_revision import (
    canonical_skill_dict,
    next_semver,
    revision_hash_of,
)


class TestNextSemver:
    def test_first_approval_reserves_minor_zero(self):
        assert next_semver(None, "patch") == "0.1.0"
        assert next_semver(None, "minor") == "0.1.0"
        # Even a 'major' bump from no prior version defaults to 0.1.0 so
        # that 1.0.0 remains an explicit curator decision.
        assert next_semver(None, "major") == "0.1.0"

    def test_patch_increments_last_segment(self):
        assert next_semver("0.1.0", "patch") == "0.1.1"
        assert next_semver("1.2.3", "patch") == "1.2.4"

    def test_minor_zeroes_patch(self):
        assert next_semver("1.2.3", "minor") == "1.3.0"
        assert next_semver("0.1.5", "minor") == "0.2.0"

    def test_major_zeroes_minor_and_patch(self):
        assert next_semver("0.9.9", "major") == "1.0.0"
        assert next_semver("1.2.3", "major") == "2.0.0"

    def test_rejects_invalid_prior_semver(self):
        with pytest.raises(ValueError):
            next_semver("1.2", "patch")
        with pytest.raises(ValueError):
            next_semver("not.a.version", "minor")


class TestRevisionHashStability:
    """Revision hashes must be content-stable across volatile metadata edits.

    The approve endpoint dedups on ``revision_hash`` across ALL curated
    rows (including deprecated). If editing ``submission_note`` or
    ``parent_curated_id`` shifted the hash, a curator could re-approve
    logically identical content as a fresh row — defeating history.
    """

    def _base(self) -> dict:
        return {
            "id": "skill_abc",
            "name": "echo",
            "description": "Echoes input",
            "semver": "0.1.0",
            "trigger_type": "keyword",
            "trigger_patterns": ["echo"],
            "tools": ["terminal"],
            "prompt_template": "Say it back.",
            "full_content": "# Echo\nYou repeat user input verbatim.",
            "metadata": {},
            "scope": "project",
        }

    def test_volatile_fields_do_not_affect_hash(self):
        a = self._base()
        b = dict(self._base(), parent_curated_id="curated_old", revision_hash="stale")
        assert revision_hash_of(a) == revision_hash_of(b)

    def test_substantive_field_changes_hash(self):
        a = self._base()
        b = dict(self._base(), prompt_template="Say it back twice.")
        assert revision_hash_of(a) != revision_hash_of(b)

    def test_canonical_dict_strips_volatile(self):
        payload = dict(
            self._base(),
            parent_curated_id="curated_old",
            revision_hash="stale-hash",
            version_label="0.0.9",
        )
        canon = canonical_skill_dict(payload)
        assert "parent_curated_id" not in canon
        assert "revision_hash" not in canon
        assert "version_label" not in canon
        # canonical_json sorts keys for deterministic hashing.
        from src.application.services.skill_revision import canonical_json

        assert canonical_json(payload) == canonical_json(self._base())
