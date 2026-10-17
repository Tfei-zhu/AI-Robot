"""S0 only: fail any attempted network connection before it can reach a provider."""
import os
import sys


def reject_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        # Do not record addresses, headers, or credentials.
        with open(os.environ["S0_NETWORK_AUDIT"], "a", encoding="utf-8") as audit:
            audit.write(event + " blocked\n")
        raise RuntimeError("S0_OFFLINE_NETWORK_BLOCKED")


sys.addaudithook(reject_network)
