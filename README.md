# AI Customer Support Agent

A 24/7 chat assistant for online stores (Shopify, WooCommerce, any website). It:

- answers questions about **delivery, returns and products**, using only your store's information
- **checks order status** (the customer gives their order number + email)
- **hands difficult conversations to staff** by creating a ticket (and optionally pinging Slack)

```
 Shop website                 Your server (this project)                 Anthropic
┌──────────────┐  /api/chat  ┌──────────────────────────────┐          ┌─────────┐
│ chat widget  │ ──────────▶ │ FastAPI ─▶ SupportAgent loop │ ◀──────▶ │ Claude  │
│ (widget.js)  │ ◀────────── │   tools: get_order_status    │          └─────────┘
└──────────────┘             │          search_products     │──▶ Shopify / WooCommerce API
                             │          escalate_to_human   │──▶ tickets.jsonl + Slack
                             └──────────────────────────────┘
```

## Project layout

| File | What it does |
|---|---|
| `knowledge/store_policies.md` | Your delivery/returns/payment rules. **The agent only answers from this.** |
| `knowledge/products.json` | Your product catalogue |
| `app/agent.py` | The system prompt and the Claude tool-use loop |
| `app/tools.py` | The 3 tools Claude can call |
| `app/orders.py` | Order-data connectors: mock, Shopify, WooCommerce |
| `app/escalation.py` | Creates staff tickets (+ Slack message) |
| `app/main.py` | Web server: `/api/chat`, `/widget.js`, demo page |
| `static/widget.js` | The chat bubble you paste into a store |
| `chat_cli.py` | Chat with the agent in your terminal |

---

## Step 1: Run it on your computer (demo data)

```bash
cd support-agent
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Get an API key at https://platform.claude.com, put it in `.env` as `ANTHROPIC_API_KEY=...`, then:

```bash
python chat_cli.py                 # chat in the terminal
uvicorn app.main:app --reload      # or open http://localhost:8000 and use the chat bubble
pytest -q                          # tests (no API key needed)
```

Try: "Where is order 1002? My email is alex@example.com" · "Can I return a personalised mug?" ·
"My mug arrived broken, I want a person". Tickets appear in `data/tickets.jsonl`.

### Or run it as a Streamlit app

```bash
streamlit run streamlit_app.py
```

**Deploy free on Streamlit Community Cloud:**
1. Push this project to a GitHub repository.
2. Go to https://share.streamlit.io → **Create app** → pick the repo, branch `main`, main file `streamlit_app.py`.
   Under **Advanced settings**, choose Python 3.12.
3. In **Advanced settings → Secrets** paste ONE of these (see `.streamlit/secrets.toml.example`):
   ```toml
   # Groq
   GROQ_API_KEY = "gsk_..."
   GROQ_MODEL = "llama-3.3-70b-versatile"
   STORE_NAME = "Demo Store"
   ```
   ```toml
   # Claude (Anthropic)
   ANTHROPIC_API_KEY = "sk-ant-..."
   STORE_NAME = "Demo Store"
   ```
   The app uses Groq automatically when only `GROQ_API_KEY` is set. If you set both keys, add `LLM_PROVIDER = "groq"` to choose Groq.
4. Deploy. You get a public `https://<name>.streamlit.app` link to show store owners.

Note: on Streamlit Cloud, files written at runtime (like `data/tickets.jsonl`) are wiped when the app restarts.
That's fine for a demo; use the Slack webhook or a database for real hand-offs.
The website chat bubble (`widget.js`) needs the FastAPI server below, not Streamlit.

## Step 2: Teach it about YOUR store

1. Rewrite `knowledge/store_policies.md` with your real delivery, returns, payment and contact info.
   Be specific: anything not written there, the agent will hand to staff instead of guessing.
2. Replace `knowledge/products.json` with your products (export from Shopify/WooCommerce as CSV and convert,
   or ask me to write a sync script).
3. Set `STORE_NAME` and `SUPPORT_EMAIL` in `.env`.
4. Test the tricky questions your customers really ask. Adjust the policies file until the answers are right.

## Step 3: Connect real order data

**Shopify**
1. Shopify admin → Settings → Apps and sales channels → Develop apps → Create an app.
2. Admin API scopes: `read_orders` (and `read_products` for later). Install the app and copy the Admin API access token.
3. In `.env`: `ORDER_BACKEND=shopify`, `SHOPIFY_STORE_DOMAIN=yourstore.myshopify.com`, `SHOPIFY_ADMIN_TOKEN=shpat_...`

**WooCommerce**
1. WooCommerce → Settings → Advanced → REST API → Add key, permission **Read**.
2. In `.env`: `ORDER_BACKEND=woocommerce`, `WC_STORE_URL=https://yourstore.com`, `WC_CONSUMER_KEY=ck_...`, `WC_CONSUMER_SECRET=cs_...`
3. Tracking numbers are read from the "Shipment Tracking" plugin if you use it.

Privacy: the agent only shows an order if the email matches, and gives the same reply for "wrong email" and
"no such order", so nobody can look up other people's orders by guessing numbers.

## Step 4: Hand-off to staff

Every hand-off is saved in `data/tickets.jsonl`. For instant alerts, create a Slack *Incoming Webhook*
and set `ESCALATION_WEBHOOK_URL`. Later you can send tickets to Gorgias / Zendesk / Freshdesk / email
instead: change `app/escalation.py`.

## Step 5: Put it online and add it to the store

1. Deploy this folder to a host that runs Python (Render, Railway, Fly.io, a VPS). Start command:
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Add your `.env` values as the host's environment variables.
2. Set `ALLOWED_ORIGINS=https://yourstore.com,https://yourstore.myshopify.com`
3. Add the widget, one line:

```html
<script src="https://YOUR-SERVER/widget.js" data-title="Help" data-color="#2f6f5e" defer></script>
```

- **Shopify:** Online Store → Themes → ⋯ → Edit code → `layout/theme.liquid` → paste just before `</body>`.
- **WooCommerce/WordPress:** install the free "WPCode" plugin → Add snippet → HTML → Site-wide footer.

Before real traffic: conversations are stored in memory, so they reset when the server restarts and don't share across
multiple servers. Move them to Redis or a database when you scale.

## Costs and settings

- `AGENT_MODEL=claude-opus-5-5` (default, most capable). For a high-volume, FAQ-heavy store, try
  `claude-haiku-5-5`, which costs a fraction as much; test it with your real questions first.
- `AGENT_EFFORT=low` keeps replies fast and cheap. Raise to `medium` if answers seem careless.
- The system prompt (your policies) is cached automatically, so repeat requests cost less.

## Ideas for later (selling this to stores)

- Multi-store: one server, a config + knowledge folder per client store, keyed by a site ID in the widget tag
- Admin dashboard: view conversations and tickets, edit policies without touching files
- Shopify App Store app (theme app extension instead of pasting a script tag), WordPress plugin for WooCommerce
- Product sync from the store API, order-confirmation email lookups, returns initiation, multilingual analytics
