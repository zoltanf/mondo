"""Tests for mondo.logging_ — token redaction in log records."""

from __future__ import annotations

import io

from mondo.logging_ import configure_logging, redact, register_secret


class TestRedact:
    def test_redacts_registered_secret(self) -> None:
        register_secret("supersecret-token-value-12345")
        assert redact("Authorization: supersecret-token-value-12345") == "Authorization: ***"

    def test_short_secrets_are_ignored(self) -> None:
        """Registering a very short value must not turn every `a` in a log into `***`."""
        register_secret("abc")
        assert redact("abc is a common word") == "abc is a common word"

    def test_bearer_like_tokens_redacted_without_registration(self) -> None:
        # A 40-char alnum blob looks like a bearer token — redact defensively.
        blob = "eyJhbGciOiJIUzI1NiJ9abcdef01234567890XYZ"
        out = redact(f"token={blob} trailing")
        assert blob not in out
        assert "***" in out


class TestConfigureLogging:
    def test_warning_by_default_stderr(self) -> None:
        buf = io.StringIO()
        configure_logging(verbose=False, debug=False, sink=buf)
        from loguru import logger

        logger.info("quiet")
        logger.warning("loud")
        out = buf.getvalue()
        assert "loud" in out
        assert "quiet" not in out

    def test_verbose_emits_info(self) -> None:
        buf = io.StringIO()
        configure_logging(verbose=True, debug=False, sink=buf)
        from loguru import logger

        logger.info("visible")
        assert "visible" in buf.getvalue()

    def test_debug_emits_trace(self) -> None:
        buf = io.StringIO()
        configure_logging(verbose=False, debug=True, sink=buf)
        from loguru import logger

        logger.debug("deep")
        assert "deep" in buf.getvalue()

    def test_registered_secret_is_redacted_in_output(self) -> None:
        buf = io.StringIO()
        configure_logging(verbose=True, debug=False, sink=buf)
        register_secret("my-real-api-token-xyz-abc-123")
        from loguru import logger

        logger.info("Using token my-real-api-token-xyz-abc-123 for request")
        assert "my-real-api-token-xyz-abc-123" not in buf.getvalue()
        assert "***" in buf.getvalue()
