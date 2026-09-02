"""Operations: the scheduled and defensive machinery around the product.

Each module here is small and separately testable, and nothing in this package is on the
conversational path except the loop guard, which runs once per inbound call before a
conversation exists.
"""
