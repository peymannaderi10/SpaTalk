# SpaTalk portal

The control plane: agency admin, client organisations, login, billing.
A [Wasp](https://wasp.sh) app cloned from the Open SaaS template and stripped
to auth, payments, admin and email.

It owns the Postgres `public` schema and no business data. Tenants,
conversations, tracked items and usage live in the runtime and are reached
over the runtime's /internal HTTP API.

## Local development

```
cp .env.server.example .env.server        # then edit
wasp db migrate-dev
PORTAL_EMAIL_PROVIDER=Dummy wasp start
```

End-to-end tests live in `e2e-tests/`; see the README there.
