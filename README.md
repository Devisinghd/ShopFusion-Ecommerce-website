# Ecommerce Website

A Django-based e-commerce backend built for real-world online shopping workflows, including catalog management, seller tools, cart logic, checkout, authentication, and API documentation.

## Project Summary

This repository is a Django and Django REST Framework e-commerce application. It supports product browsing, seller product management, authentication, cart handling, order creation, address management, and interactive API documentation. Review the deployment checklist below before accepting live orders.

The project is designed to be practical, extensible, and deployment-ready for real-world use on cloud platforms and containerized environments.

## Why this project matters

This project demonstrates a complete backend architecture for an online store, including:

- secure user authentication with JWT
- separate seller and customer workflows
- order and checkout logic
- database-backed inventory and cart handling
- API documentation for faster onboarding
- Docker and deployment-ready configuration for modern hosting providers

## Features

- Product catalog and seller product CRUD
- Customer-facing product browsing and search
- Add-to-cart and cart update flows
- Checkout and order creation workflow
- Shipping address management
- Order history and order item tracking
- JWT authentication with access and refresh tokens
- Interactive API documentation via Swagger and ReDoc
- PostgreSQL-ready configuration
- Docker-based setup and production-friendly deployment patterns

## Tech Stack

- Python 3.11+
- Django 5.2.12
- Django REST Framework
- PostgreSQL
- djangorestframework-simplejwt
- drf-spectacular
- Gunicorn
- Docker

## Project Structure

- `myapp/` — storefront, product views, and templates
- `cart/` — cart logic and cart-related workflows
- `orders/` — order, item, and address management
- `users/` — authentication and user management
- `seller/` — seller dashboard and product management
- `mysite/` — Django settings and core project configuration
- `media/` — uploaded image storage
- `staticfiles/` — generated static assets for deployment
- `requirements.txt` — Python dependencies
- `dockerfile` — production containerization
- `docker-compose.yml` — local Docker orchestration

## Demo

Visit the [live ShopFusion storefront](https://ecommerce-website-z90m.onrender.com/).

### Storefront screenshot

![ShopFusion storefront homepage](./screenshots/storefront-home.png)

## Local Setup

1. Clone the repository

```bash
git clone https://github.com/Devisinghd/Ecommerce-website.git
cd Ecommerce-website
```

2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

3. Install dependencies

```bash
pip install -r requirements.txt
```

4. Copy environment settings

```bash
copy .env.example .env
```

5. Update `.env` for local development, or configure equivalent environment variables on your host

- `DJANGO_SECRET_KEY`
- `DATABASE_URL` (optional locally; use a PostgreSQL URL for PostgreSQL)
- `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` if email verification is enabled

6. Run database migrations

```bash
python manage.py migrate
```

7. Start the development server

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser.

## API Documentation

After starting the server, visit:

- Swagger UI: `http://localhost:8000/api/swagger-ui/`
- ReDoc: `http://localhost:8000/api/redoc/`
- OpenAPI schema: `http://localhost:8000/api/schema/`

## Deployment

The local Docker Compose file is for development. It intentionally supports SQLite when `ALLOW_SQLITE=True`. For a live deployment:

- Your SQL Shell screenshot shows PostgreSQL at `localhost:5432`, database `appdb`, user `adminuser`. That is a PostgreSQL server on your own computer, not Render's database. To use it from this Docker container, set local `.env` to `DATABASE_URL=postgresql://adminuser:<URL_ENCODED_PASSWORD>@host.docker.internal:5432/appdb` and `ALLOW_SQLITE=False`. If Django runs directly on Windows rather than inside Docker, use `localhost` instead of `host.docker.internal`. Keep PostgreSQL restricted to local/Docker access; do not expose port 5432 to the public internet.
- Apply `python manage.py migrate` after switching databases. Migrations create the schema but do not copy your existing SQLite users, products, orders, or uploaded images. Export/import those separately if you need to retain them.
- Your local PostgreSQL server is for local development only. A Render-hosted app cannot reach your computer's `localhost`; configure a Render PostgreSQL database and set that database's **Internal Database URL** in the Render web service environment. Keep the local `.env` and Render environment variables separate.
- Set `DEBUG=False`, a unique `DJANGO_SECRET_KEY`, the real `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS`.
- Set `DATABASE_URL` to the managed PostgreSQL connection URL. On Render, use the PostgreSQL **Internal Database URL** in the web service's environment when the web service and database are in the same Render region/private network. Do not put the URL in source control.
- Use the **External Database URL** only for connections from outside Render, such as local Docker. The internal hostname is private to Render and normally cannot resolve or connect from a developer machine.
- Configure working SMTP credentials when `EMAIL_VERIFICATION=True`; production uses SMTP rather than silently printing verification codes to logs.
- Set `DEFAULT_FROM_EMAIL` to the authenticated Gmail address or another sender verified with your SMTP provider. If unset, the app uses `EMAIL_HOST_USER` as the sender.
- Keep uploaded media on a persistent disk or object-storage service. Container filesystems may be ephemeral; point `MEDIA_ROOT` at the persistent mount path.
- Configure HTTPS at the host/proxy. `SECURE_SSL_REDIRECT` defaults to enabled outside debug mode; set the host's trusted CSRF origins and validate the reverse-proxy HTTPS header.
- `check --deploy` may warn about HSTS subdomain/preload settings. Only enable these after confirming every relevant subdomain is HTTPS-only; preload enrollment affects browsers beyond this app.
- Run migrations and collect static assets during release/deployment:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

The application refuses to start in non-debug mode without `DATABASE_URL` unless `ALLOW_SQLITE=True` is explicitly set. Do not set `ALLOW_SQLITE=True` on a live service.

### Razorpay payments

- First enable/activate your Razorpay account and finish any account verification Razorpay requires. In the Razorpay Dashboard, use **Test Mode** to create test API keys. Set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` in the local `.env` for local testing and run a complete checkout with Razorpay's current test payment details. Never commit the real `.env` file.
- Configure a Test Mode webhook pointing to `https://<your-test-domain>/orders/payment/webhook/`, subscribe to `payment.captured`, and set the webhook's signing secret as `RAZORPAY_WEBHOOK_SECRET`. This webhook secret is separate from the API key secret. The endpoint must be publicly reachable over HTTPS for Razorpay to deliver webhooks; localhost is not reachable by Razorpay.
- After test payments and webhook delivery both work, switch the Dashboard to **Live Mode**, create live API keys, and configure the live webhook at `https://<your-live-domain>/orders/payment/webhook/`. Set the live `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and live webhook `RAZORPAY_WEBHOOK_SECRET` in the Render web service environment, then redeploy/restart. Test and live keys/secrets are different; do not mix them.
- Confirm successful and failed payments, callback verification, webhook delivery, duplicate webhook retries, and the resulting order/payment status in the live deployment before accepting customer orders.
- Checkout creates an order on the server, verifies the Razorpay callback signature and payment amount/currency, captures authorized payments, and accepts signed captured-payment webhooks idempotently.
- Orders reserve stock immediately. Customers can cancel an unpaid order before a Razorpay payment order has been created; once payment is started, cancellation is blocked to avoid a payment/stock race. Add and operate an unpaid-order expiry and refund/reconciliation policy before relying on the store for live fulfillment.
- Do not treat an order as paid based only on the browser callback; the application records payment only after server-side verification.

## Contribution Guidelines

Contributions are welcome. Please read [CONTRIBUTING.md](./CONTRIBUTING.md) before submitting changes.

We also provide a set of beginner-friendly task ideas in [GOOD_FIRST_ISSUES.md](./GOOD_FIRST_ISSUES.md).

## Code of Conduct

Please review our community expectations in [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).

## License

This project is licensed under the [MIT License](./LICENSE).

## Resume-Friendly Summary

This project is a Django-based e-commerce backend with secure JWT authentication, product management, cart workflows, checkout and order handling, address tracking, and API documentation. It combines backend architecture, deployment readiness, and real-world business logic in a practical full-stack portfolio project.

## Author

Developed by Devisingh Dangi.
