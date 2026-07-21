"""Shared fixtures for the observability-aiops test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_approver(monkeypatch):
    """Record a synthetic approver annotation globally.

    The harness authorizes nothing, so this gates nothing; it only ensures the
    optional ``approved_by`` audit field is populated for tests that do not set
    their own. The governance-persistence tests clear it to show the annotation
    is genuinely optional."""
    monkeypatch.setenv("OBSERVABILITY_AUDIT_APPROVED_BY", "pytest")
