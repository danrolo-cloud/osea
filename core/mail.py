"""
Email sending with a safety net.

Demo and test data use reserved addresses (".example", example.org and similar)
that can never belong to a real person. This backend quietly drops those
recipients before handing the message to the real mail server, so a fictional
address can never cause a real send, even by mistake. Everything else is the
standard Django SMTP backend.
"""

import logging

from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

logger = logging.getLogger(__name__)

# Reserved for documentation and testing (RFC 2606 / RFC 6761); never deliverable to a real person.
RESERVED_DOMAINS = ("example", "test", "invalid", "localhost", "example.com", "example.net", "example.org")


def is_reserved(address):
    """True for an address at a reserved domain or any sub-domain of one."""
    domain = address.rsplit("@", 1)[-1].strip().strip(">").lower()
    return any(domain == reserved or domain.endswith("." + reserved) for reserved in RESERVED_DOMAINS)


class SafeSMTPBackend(SMTPBackend):
    def send_messages(self, email_messages):
        to_send = []
        for message in email_messages:
            dropped = [a for a in message.recipients() if is_reserved(a)]
            if dropped:
                message.to = [a for a in message.to if not is_reserved(a)]
                message.cc = [a for a in message.cc if not is_reserved(a)]
                message.bcc = [a for a in message.bcc if not is_reserved(a)]
                logger.info("Not sending to %d fictional address(es): %s", len(dropped), message.subject)
            if message.recipients():
                to_send.append(message)
        if not to_send:
            return 0
        return super().send_messages(to_send)
