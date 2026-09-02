"""Instagram and Facebook Page plumbing: OAuth, encrypted tokens, Graph calls, webhooks.

Nothing in this package answers a customer. The adapters turn a Meta event into a call on
:class:`spatalk.text.service.TextConversationService` and send that service's reply back
through the Graph API, so Instagram and Messenger inherit the one brain, the guard, the
rules gate, the tracked-item outcomes and human takeover without a second implementation.
"""
