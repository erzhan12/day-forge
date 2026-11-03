"""Tests for the personal daily-export token lifecycle (feature 0088).

Covers creation, lookup/authentication, revocation, recreation, inactive-user
rejection, owner isolation, and user-deletion cascade. The raw credential must
never be persisted; only its SHA-256 digest is stored.
"""

import pytest
from django.contrib.auth.models import User
from schedules.export_tokens import (
    TOKEN_PREFIX,
    TokenExistsError,
    authenticate,
    create_token,
    generate_raw_token,
    hash_token,
    revoke_token,
)
from schedules.models import PersonalExportToken

pytestmark = pytest.mark.django_db


def test_create_token_returns_prefixed_credential_with_enough_entropy(user):
    raw_token, row = create_token(user.pk)
    assert raw_token.startswith(TOKEN_PREFIX)
    # Prefix plus base64url(32 random bytes) is well over 32 chars.
    assert len(raw_token) > len(TOKEN_PREFIX) + 32
    assert row.user_id == user.pk


def test_created_row_persists_only_the_digest_never_the_raw_value(user):
    raw_token, row = create_token(user.pk)
    row.refresh_from_db()
    assert row.token_digest == hash_token(raw_token)
    assert row.token_digest != raw_token
    assert raw_token not in row.token_digest
    assert len(row.token_digest) == 64


def test_authenticate_resolves_the_owning_user(user):
    raw_token, _ = create_token(user.pk)
    assert authenticate(raw_token) == user


def test_authenticate_rejects_unknown_or_malformed_tokens(user):
    create_token(user.pk)
    assert authenticate("garbage") is None
    assert authenticate("") is None
    assert authenticate(TOKEN_PREFIX + "not-a-real-token") is None


def test_authenticate_rejects_inactive_user(user):
    raw_token, _ = create_token(user.pk)
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert authenticate(raw_token) is None


def test_create_twice_without_revoking_raises_and_does_not_replace(user):
    raw_token, _ = create_token(user.pk)
    with pytest.raises(TokenExistsError):
        create_token(user.pk)
    # Original token still authenticates; only one row remains.
    assert authenticate(raw_token) == user
    assert PersonalExportToken.objects.filter(user=user).count() == 1


def test_revoke_deletes_the_row_and_disables_authentication(user):
    raw_token, _ = create_token(user.pk)
    revoke_token(user.pk)
    assert not PersonalExportToken.objects.filter(user=user).exists()
    assert authenticate(raw_token) is None


def test_revoke_is_idempotent_when_no_token_exists(user):
    revoke_token(user.pk)  # Must not raise.
    revoke_token(user.pk)


def test_recreation_after_revoke_produces_an_unrelated_credential(user):
    first_raw, _ = create_token(user.pk)
    revoke_token(user.pk)
    second_raw, row = create_token(user.pk)
    assert second_raw != first_raw
    assert hash_token(second_raw) != hash_token(first_raw)
    assert authenticate(first_raw) is None
    assert authenticate(second_raw) == user
    assert PersonalExportToken.objects.filter(user=user).count() == 1
    assert row.token_digest == hash_token(second_raw)


def test_owner_isolation_between_two_users_tokens(user):
    other = User.objects.create_user(username="other-export-owner")
    raw_user, _ = create_token(user.pk)
    raw_other, _ = create_token(other.pk)
    assert authenticate(raw_user) == user
    assert authenticate(raw_other) == other
    assert hash_token(raw_user) != hash_token(raw_other)


def test_user_deletion_cascades_to_token(user):
    raw_token, _ = create_token(user.pk)
    user_id = user.pk
    user.delete()
    assert not PersonalExportToken.objects.filter(user_id=user_id).exists()
    assert authenticate(raw_token) is None


def test_generated_tokens_are_unique_across_many_calls():
    raws = {generate_raw_token() for _ in range(1000)}
    assert len(raws) == 1000
    digests = {hash_token(r) for r in raws}
    assert len(digests) == 1000
