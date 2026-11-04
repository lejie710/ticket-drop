"""HTTP API and static file serving."""

import re
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Path as PathParam, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from . import auth, db, faults, service
from .clock import Clock
from .config import Settings
from .ratelimit import FailureWindow, TokenBucket

SEAT_ID_PATTERN = r"^[A-T]-\d{2}$"
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
STATIC_DIR = Path(__file__).parent / "static"

EVENT = {
    "artist": "Halcyon Static",
    "tour": "Neon Tide Tour",
    "venue": "Harbourfront Hall",
    "starts_at": "2027-03-13T20:00:00+08:00",
}

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Strict):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    password: str = Field(min_length=1, max_length=128)


class SeatIn(Strict):
    seat_id: str = Field(pattern=SEAT_ID_PATTERN)


class CheckoutIn(Strict):
    card_number: str = Field(pattern=r"^[0-9 ]{12,23}$")


class CheckoutWithAmountIn(CheckoutIn):
    # Used only by the client_sets_amount fault.
    amount_cents: int | None = None


# Faults the browser must know about. Exposed in /api/event only when enabled.
FRONTEND_FAULTS = ("map_stale_after_failed_seat_change",)


class ClockIn(Strict):
    advance_ms: int | None = None
    freeze_at_ms: int | None = None


def error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    clock = clock or Clock()
    db.initialise(settings.db_path)

    app = FastAPI(title="Ticket Drop", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.clock = clock
    hold_limiter = TokenBucket(settings.hold_rate_per_second, settings.hold_burst)
    login_failures = FailureWindow(settings.failed_logins_per_minute, 60)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(service.BookingError)
    async def booking_error(request, exc: service.BookingError):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(ApiError)
    async def api_error(request, exc: ApiError):
        return error(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc: Exception):
        # Same error shape as every other answer, and no internals in the message.
        # This answer is built outside the middleware stack, so it adds the headers itself.
        return error(500, "server_error", "Something went wrong on the server. Try again; "
                                          "repeating a payment with the same attempt never charges twice.",
                     {**SECURITY_HEADERS, "Cache-Control": "no-store"})

    def api_route_for_other_method(scope) -> list[str]:
        """The methods an API route accepts at this path, or [] if no API route has this path."""
        allowed = []
        for route in app.router.routes:
            if isinstance(route, APIRoute) and route.matches(scope)[0] == Match.PARTIAL:
                allowed += sorted(route.methods)
        return allowed

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        # Unknown /api addresses fall through to the static files, which answer 404 or 405
        # in FastAPI's own shape. Under /api, answer in the single error shape instead.
        if not request.url.path.startswith("/api/") or exc.status_code not in (404, 405):
            return await http_exception_handler(request, exc)
        allowed = api_route_for_other_method(request.scope)
        if allowed:
            return error(405, "method_not_allowed", "This address does not accept that method.",
                         {"Allow": ", ".join(allowed)})
        return error(404, "not_found", "There is nothing at this address.")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        return error(422, "invalid_request", "The request is not valid: " + ", ".join(fields))

    def connection():
        conn = db.connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def current_user(authorization: str | None = Header(default=None), conn=Depends(connection)):
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "not_signed_in", "Sign in to continue.")
        user = auth.user_for_token(conn, authorization.removeprefix("Bearer "))
        if user is None:
            raise ApiError(401, "not_signed_in", "Your session has ended. Sign in again.")
        return user

    def limit_seat_changes(request: Request, user=Depends(current_user)):
        key = str(user["id"])
        if faults.on(settings, "seat_rate_limit_per_session"):
            key = request.headers.get("authorization", "")
        wait = hold_limiter.take(key, time.monotonic())
        if wait:
            raise ApiError(429, "too_many_requests", "Too many seat changes. Wait a moment and try again.",
                           {"Retry-After": str(max(1, round(wait + 0.5)))})
        return user

    @app.get("/api/event")
    def event():
        now = clock.now_ms()
        body = {
            **EVENT,
            "sale_opens_at_ms": settings.sale_opens_at_ms,
            "sale_open": service.sale_is_open(settings, now),
            "server_now_ms": now,
            "max_seats": settings.max_seats,
            "hold_seconds": settings.hold_seconds,
            "prices_cents": {str(k): v for k, v in db.PRICES_CENTS.items()},
        }
        frontend_faults = [name for name in FRONTEND_FAULTS if faults.on(settings, name)]
        if frontend_faults:
            body["faults"] = frontend_faults
        return body

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, conn=Depends(connection)):
        address = request.client.host if request.client else "unknown"
        wait = login_failures.retry_after(address, time.monotonic())
        if wait:
            raise ApiError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again later.",
                           {"Retry-After": str(wait)})
        result = auth.login(conn, body.username, body.password, clock.now_ms())
        if result is None:
            login_failures.record(address, time.monotonic())
            raise ApiError(401, "wrong_credentials", "The username or password is wrong.")
        return result

    @app.post("/api/logout", status_code=204)
    def logout(authorization: str = Header(), user=Depends(current_user), conn=Depends(connection)):
        auth.logout(conn, authorization.removeprefix("Bearer "))
        return Response(status_code=204)

    @app.get("/api/me")
    def me(user=Depends(current_user)):
        return {"username": user["username"], "display_name": user["display_name"]}

    @app.get("/api/seats")
    def seats(user=Depends(current_user), conn=Depends(connection)):
        return {"seats": service.seat_map(conn, settings, clock, user["id"]), "server_now_ms": clock.now_ms()}

    @app.get("/api/hold")
    def get_hold(user=Depends(current_user), conn=Depends(connection)):
        return {"hold": service.get_hold(conn, settings, clock, user["id"]), "server_now_ms": clock.now_ms()}

    @app.post("/api/hold/seats")
    def add_seat(body: SeatIn, user=Depends(limit_seat_changes), conn=Depends(connection)):
        hold = service.add_seat(conn, settings, clock, user["id"], body.seat_id)
        return {"hold": hold, "server_now_ms": clock.now_ms()}

    @app.delete("/api/hold/seats/{seat_id}")
    def remove_seat(seat_id: str = PathParam(pattern=SEAT_ID_PATTERN), user=Depends(limit_seat_changes),
                    conn=Depends(connection)):
        hold = service.remove_seat(conn, settings, clock, user["id"], seat_id)
        return {"hold": hold, "server_now_ms": clock.now_ms()}

    @app.delete("/api/hold", status_code=204)
    def release(user=Depends(limit_seat_changes), conn=Depends(connection)):
        service.release_hold(conn, settings, clock, user["id"])
        return Response(status_code=204)

    checkout_model = CheckoutIn
    if faults.on(settings, "client_sets_amount"):
        checkout_model = CheckoutWithAmountIn

    @app.post("/api/checkout")
    def checkout(body: checkout_model, idempotency_key: str | None = Header(default=None),
                 user=Depends(current_user), conn=Depends(connection)):
        if not idempotency_key or not IDEMPOTENCY_KEY.match(idempotency_key):
            raise ApiError(400, "invalid_idempotency_key",
                           "Send an Idempotency-Key header of 8 to 64 letters, digits, '-' or '_'.")
        if faults.on(settings, "client_sets_amount"):
            status, payload = service.checkout(conn, settings, clock, user["id"], idempotency_key, body.card_number,
                                               client_amount_cents=body.amount_cents)
            return JSONResponse(payload, status_code=status)
        status, payload = service.checkout(conn, settings, clock, user["id"], idempotency_key, body.card_number)
        return JSONResponse(payload, status_code=status)

    @app.get("/api/tickets")
    def tickets(user=Depends(current_user), conn=Depends(connection)):
        return {"tickets": service.list_tickets(conn, user["id"])}

    @app.get("/api/tickets/{ticket_id}")
    def ticket(ticket_id: str = PathParam(pattern=r"^[0-9a-f]{32}$"), user=Depends(current_user),
               conn=Depends(connection)):
        return service.get_ticket(conn, user["id"], ticket_id)

    if settings.test_hooks:
        @app.post("/api/_test/clock")
        def set_clock(body: ClockIn):
            if body.freeze_at_ms is not None:
                clock.freeze(body.freeze_at_ms)
            if body.advance_ms is not None:
                clock.advance(body.advance_ms)
            return {"server_now_ms": clock.now_ms()}

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app
