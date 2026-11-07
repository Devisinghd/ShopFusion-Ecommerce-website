# ShopFusion

ShopFusion is a Django e-commerce application with a storefront, customer accounts, seller product management, cart and checkout flows, and REST API endpoints.

## Features

- Product catalog, search, category browsing, and product detail pages
- User registration, email verification, login, logout, and profiles
- Shopping cart with quantity and price updates
- Delivery addresses, checkout, order history, and order cancellation
- Razorpay payment order creation and payment verification
- Seller dashboard and seller-owned product management
- JWT authentication and OpenAPI documentation
- PostgreSQL support, Cloudinary media storage, and static file collection

## Tech Stack

- Python 3 and Django 5.2
- Django REST Framework
- PostgreSQL or SQLite
- djangorestframework-simplejwt
- drf-spectacular
- Cloudinary
- WhiteNoise
- Razorpay
- Docker

## Project Structure

```text
myapp/       Storefront, product views, templates, and API views
cart/        Shopping cart views
orders/      Checkout, addresses, payments, and order views
seller/      Seller dashboard and product management
users/       Registration, authentication, and profiles
mysite/      Django settings, URLs, and checks
requirements.txt
build.sh
vercel.json
```

## Local Setup

Python 3.11 or newer is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

For Docker:

```powershell
docker compose up --build
```

The web container listens on `127.0.0.1:8000`.

## Environment Variables

Copy `.env.example` to `.env` for local settings.

Required in production:

```text
DJANGO_SECRET_KEY
DATABASE_URL
ALLOWED_HOSTS
CSRF_TRUSTED_ORIGINS
```

Database settings:

```text
ALLOW_SQLITE=False
SQLITE_PATH=db.sqlite3
```

Cloudinary media storage:

```text
CLOUDINARY_CLOUD_NAME
CLOUDINARY_API_KEY
CLOUDINARY_API_SECRET
```

Payment settings:

```text
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
```

Email settings:

```text
EMAIL_BACKEND
BREVO_API_KEY
DEFAULT_FROM_EMAIL
EMAIL_VERIFICATION
```

Cloudinary variables are optional only when local file storage is acceptable. Payment and email features require valid provider credentials.

## Running Locally

```powershell
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py runserver
```

Useful URLs:

- Storefront: `http://127.0.0.1:8000/`
- Django admin: `http://127.0.0.1:8000/admin/`
- OpenAPI schema: `http://127.0.0.1:8000/api/schema/`
- Swagger UI: `http://127.0.0.1:8000/api/swagger-ui/`
- ReDoc: `http://127.0.0.1:8000/api/redoc/`

## API Authentication

The API provides JWT access and refresh tokens at `/api/token/` and `/api/token/refresh/`.

Send the access token on authenticated requests:

```text
Authorization: Bearer <access_token>
```

API routes:

```text
POST /api/auth/register/
POST /api/auth/verify-email/
GET, PATCH /api/profile/
POST /api/cart/quote/
POST /api/checkout/
POST /api/orders/<order_id>/start-payment/
POST /api/orders/<order_id>/verify-payment/
POST /api/orders/<order_id>/cancel/
```

Product routes are available under `/api/products/`. Product and order permissions are enforced by the API view classes.

## Deployment

Set `DEBUG=False`, `DJANGO_SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS` in production. Use managed PostgreSQL rather than SQLite for persistent data.

Configure Cloudinary with the environment variables listed above. Run migrations and collect static assets during deployment:

```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear
```

Static output belongs in `STATIC_ROOT` and media uploads should not be stored in generated application directories.

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE).
