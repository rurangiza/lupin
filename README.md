# Lupin

A personal assistant you can reach from your phone. The first interface is Telegram. Phone calls, WhatsApp and a Chrome extension come later, as extra adapters around the same core.

## How it fits together

```
 Telegram ──► channels/telegram ──┐
 (later) phone ─► channels/voice ─┤   InboundMessage    ┌───────────┐     ┌─────────┐
 (later) WhatsApp, Chrome ext ────┼───────────────────► │ Assistant │ ──► │  Agent  │ ──► OpenAI
 curl / Bruno ─► channels/debug ──┘ ◄── Reply ───────── └─────┬─────┘     └────┬────┘
                                                              │                │
                                                         Postgres          web_search
                                          (users, identities, conversations, messages)
```

- **Channels** turn their own payloads into one `InboundMessage` and render the reply back. Nothing outside `channels/` knows about Telegram.
- **Assistant** handles one message end to end: it checks the sender is known, drops duplicate deliveries, loads the conversation and saves the turn.
- **Agent** runs the model/tool loop and streams events (`TextDelta`, `ToolCallStarted`, `ToolCallFinished`, `Done`). Telegram collects them into one message. A voice channel will forward the text deltas to speech as they arrive.
- **Identity** is a table: `(channel, external_id) → user`. Today it holds your Telegram id. Senders without a row get no reply, and the bot doesn't even show "typing". Multi-tenancy later means adding rows, not changing code.

## Run it locally

You need Docker, a bot token from [@BotFather](https://t.me/BotFather), your numeric Telegram user id (ask [@userinfobot](https://t.me/userinfobot)), and an OpenAI key. A [Tavily](https://tavily.com) key enables web search.

```sh
cp .env.example .env     # fill in the keys and your Telegram id
docker compose up --build
```

Message your bot. It answers from your machine. `/new` starts a fresh conversation.

The stack is `db` (Postgres 17), `migrate` (runs `alembic upgrade head`, then exits) and `api`. They share the `lupin` network and reach each other by service name. Only the API is published, on `127.0.0.1:8080`.

### Reaching a local app from Telegram

There are two modes, set with `TELEGRAM_MODE`. Telegram allows only one at a time, and the app switches automatically at startup.

| Mode | How it works | Needs |
|---|---|---|
| `polling` (default) | The app asks Telegram for new messages. All traffic is outbound. | Nothing. Works behind any router. |
| `webhook` | Telegram pushes each message to a public HTTPS URL. This is the production path. | A tunnel or a public URL |

To try the webhook path locally, set `TELEGRAM_MODE=webhook` and a `TELEGRAM_WEBHOOK_SECRET` (`openssl rand -hex 32`), then run:

```sh
docker compose --profile tunnel up --build
```

This starts a [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) to the API. The app reads the random `*.trycloudflare.com` URL from cloudflared's metrics endpoint and registers it with Telegram itself, so restarts need no manual step. Requests without the secret header are rejected. With a stable URL (a named tunnel or a load balancer), set `PUBLIC_BASE_URL` instead.

The phone channel will need this inbound path too: Twilio can't poll.

### Without Telegram

With `DEBUG_API_ENABLED=true`, `POST /debug/chat` goes through the same assistant on its own `debug` channel:

```sh
curl -s localhost:8080/debug/chat -H 'content-type: application/json' -d '{"text": "hello"}'
```

The Bruno collection in `backend/bruno` has the same request.

## Develop

```sh
cd backend
uv sync
uv run pytest            # no network or Postgres needed: fake LLM, SQLite
uv run ruff check . && uv run ruff format --check .
```

To change the schema, edit `storage/models.py`, then run `uv run alembic revision --autogenerate -m "..."` with the database port published (see `compose.yaml`). CI runs `alembic check` against Postgres to catch models and migrations drifting apart.

### Layout

```
backend/src/lupin/
├── main.py          app wiring, lifespan, /healthz
├── config.py        all settings, from environment variables
├── assistant.py     one message in, one reply out
├── core/
│   ├── agent.py     model/tool loop, streams events
│   ├── llm/         provider-neutral protocol + OpenAI implementation
│   ├── tools/       tool base and registry (timeouts, errors fed back to the model), web_search
│   └── prompts.py
├── domain/          InboundMessage, ChatMessage, Channel, Capabilities
├── storage/         SQLAlchemy models and queries
└── channels/
    ├── telegram/    Bot API client, adapter, formatting, polling and webhook
    └── debug/       HTTP endpoint for local testing
```

### Adding a channel

1. Add a value to `Channel`.
2. Create `channels/<name>/`. Convert inbound payloads to `InboundMessage` with an `event_id` that is unique per delivery, call `Assistant.handle`, and send `Reply.text` back.
3. Set `Capabilities` so the prompt fits the medium (`voice=True` asks for short spoken sentences).
4. Add the owner's identity for that channel in `main.py`.

## Roadmap

- **Iteration 2:** deploy the same image with Terraform (AWS ECS + RDS, or Cloudflare), with secrets from a secret manager instead of `.env`.
- Phone calls through a number (Twilio media streams + a realtime model), sharing tools and memory.
- WhatsApp, Chrome extension, more tools, multi-tenancy.

Known limit: the per-chat lock that keeps turns in order is in-process. Running more than one API replica will need a database lock.
