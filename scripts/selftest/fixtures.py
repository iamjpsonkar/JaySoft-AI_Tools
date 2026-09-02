"""
Scratch-repo fixtures for the JSAT self-test.

The original self-test indexed two trivial Python files, which meant most
analysis tools were asked a question with no possible answer and "passed"
vacuously. This module builds one repo that has real material for every
tool: six languages so all six parsers run, a deep call chain, an inheritance
chain, HTTP route handlers, two committed versions of an OpenAPI spec so a
contract diff has two real git refs to compare, a migration with the classic
lock trap, a synthetic secret, a CVE-bearing requirements pin, and a test
file that covers exactly one of two functions so the coverage tools have a
known-correct answer to assert against.

Everything here is written to a temp dir and committed to a real git repo.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# A deliberately FAKE AWS-shaped key. jsat/_secrets.py matches
# r"\bAKIA[0-9A-Z]{16}\b", so this is AKIA followed by exactly 16 uppercase
# alphanumerics — the body spells EXAMPLE0NOTREAL9 so it reads as obviously
# synthetic. It is not now and never was a live credential. Assembled at
# runtime so this source file does not itself contain a scannable literal.
_AWS_BODY = "EXAMPLE" + "0NOTREAL" + "9"   # 16 chars
FAKE_AWS_KEY = "AKIA" + _AWS_BODY
assert len(FAKE_AWS_KEY) == 20, FAKE_AWS_KEY
FAKE_AWS_SECRET = "wJalr" + "XUtnFEMI" + "K7MDENGbPxRfiCYEXAMPLEKEY"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, check=True,
        capture_output=True, text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(repo),
            "GIT_AUTHOR_NAME": "JSAT Selftest",
            "GIT_AUTHOR_EMAIL": "selftest@example.invalid",
            "GIT_COMMITTER_NAME": "JSAT Selftest",
            "GIT_COMMITTER_EMAIL": "selftest@example.invalid",
        },
    )


OPENAPI_V1 = """\
openapi: 3.0.0
info:
  title: Payments API
  version: 1.0.0
paths:
  /payments:
    get:
      summary: List payments
      responses:
        '200':
          description: ok
    post:
      summary: Create a payment
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required:
                - amount
              properties:
                amount:
                  type: integer
                currency:
                  type: string
      responses:
        '201':
          description: created
  /refunds:
    get:
      summary: List refunds
      responses:
        '200':
          description: ok
"""

# Breaking on purpose, three ways: /refunds is deleted, and `currency`
# becomes required on POST /payments. A correct contract checker must flag
# both an endpoint removal and a newly-required field.
OPENAPI_V2 = """\
openapi: 3.0.0
info:
  title: Payments API
  version: 2.0.0
paths:
  /payments:
    get:
      summary: List payments
      responses:
        '200':
          description: ok
    post:
      summary: Create a payment
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required:
                - amount
                - currency
              properties:
                amount:
                  type: integer
                currency:
                  type: string
      responses:
        '201':
          description: created
"""

MIGRATION_SQL = """\
-- The classic full-table-rewrite trap: on PostgreSQL below 11 this takes an
-- ACCESS EXCLUSIVE lock and rewrites every row.
ALTER TABLE payments ADD COLUMN currency VARCHAR(3) NOT NULL DEFAULT 'USD';

-- A second locking operation in the same file, which a good checker should
-- also flag: two exclusive locks in one migration compound the outage.
ALTER TABLE payments ALTER COLUMN amount TYPE BIGINT;

CREATE INDEX idx_payments_created_at ON payments (created_at);
"""

PY_PAYMENTS = '''\
"""Payment service — the deep call chain the trace tools follow."""


class PaymentError(Exception):
    """Base failure for the payment domain."""


class InsufficientFunds(PaymentError):
    """Raised when the account cannot cover the charge."""


class BaseGateway:
    """Abstract payment gateway."""

    def authorize(self, amount):
        raise NotImplementedError


class StripeGateway(BaseGateway):
    """Concrete gateway, so INHERITS has a real edge to record."""

    def __init__(self, api_key):
        self.api_key = api_key

    def authorize(self, amount):
        return validate_amount(amount)


def validate_amount(amount):
    """Depth 4 of the call chain."""
    if amount <= 0:
        raise InsufficientFunds("amount must be positive")
    return True


def charge_card(amount, gateway):
    """Depth 3."""
    return gateway.authorize(amount)


def process_payment(amount, gateway=None):
    """Depth 2."""
    gateway = gateway or StripeGateway("sk_test_placeholder")
    return charge_card(amount, gateway)


def handle_payment_request(request):
    """Depth 1 — the HTTP entry point."""
    return process_payment(request.get("amount", 0))


def refund_payment(payment_id):
    """Deliberately untested, so the coverage tools have a real gap to find."""
    return {"refunded": payment_id}
'''

PY_ROUTES = '''\
"""Flask-style route handlers, so endpoint inference has real input."""
from svc_payments.payments import handle_payment_request


class app:  # noqa: N801 - stand-in for a Flask app object
    @staticmethod
    def route(path, methods=None):
        def deco(fn):
            return fn
        return deco


@app.route("/payments", methods=["POST"])
def post_payments_view(request):
    """POST /payments"""
    return handle_payment_request(request)


@app.route("/payments", methods=["GET"])
def get_payments_view(request):
    """GET /payments"""
    return {"payments": []}


@app.route("/health", methods=["GET"])
def health_view(request):
    """GET /health"""
    return {"ok": True}
'''

PY_TEST = '''\
"""Covers process_payment but NOT refund_payment — a known coverage gap."""
from svc_payments.payments import process_payment


def test_process_payment_returns_true():
    assert process_payment(100) is True
'''

PY_USERS = '''\
"""User service — a second top-level dir so service inference sees two."""


class UserRepository:
    """Reads users."""

    def find(self, user_id):
        return {"id": user_id}


def get_user(user_id):
    return UserRepository().find(user_id)
'''

JS_SRC = """\
import { formatCurrency } from './format.js';

export class Cart {
  constructor(items) {
    this.items = items;
  }

  total() {
    return this.items.reduce((a, b) => a + b.price, 0);
  }
}

export class DiscountedCart extends Cart {
  total() {
    return super.total() * 0.9;
  }
}

export function renderTotal(cart) {
  return formatCurrency(cart.total());
}
"""

TS_SRC = """\
export interface Money {
  amount: number;
  currency: string;
}

export function formatCurrency(value: number, currency: string = 'USD'): string {
  return `${currency} ${value.toFixed(2)}`;
}

export class Ledger {
  private entries: Money[] = [];

  add(entry: Money): void {
    this.entries.push(entry);
  }

  sum(): number {
    return this.entries.reduce((a, b) => a + b.amount, 0);
  }
}
"""

GO_SRC = """\
package payments

import (
\t"errors"
\t"fmt"
)

// Gateway authorizes charges.
type Gateway interface {
\tAuthorize(amount int64) error
}

// StripeGateway talks to Stripe.
type StripeGateway struct {
\tAPIKey string
}

// Authorize validates and charges.
func (g *StripeGateway) Authorize(amount int64) error {
\tif amount <= 0 {
\t\treturn errors.New("amount must be positive")
\t}
\treturn nil
}

// ProcessPayment is the entry point.
func ProcessPayment(amount int64, g Gateway) error {
\tif err := g.Authorize(amount); err != nil {
\t\treturn fmt.Errorf("authorize failed: %w", err)
\t}
\treturn nil
}
"""

JAVA_SRC = """\
package com.example.payments;

import java.util.List;
import java.util.ArrayList;

/** Abstract gateway. */
public abstract class BaseGateway {
    public abstract boolean authorize(long amount);
}

/** Concrete gateway implementing a marker interface. */
class StripeGateway extends BaseGateway implements Runnable {
    private final String apiKey;

    public StripeGateway(String apiKey) {
        this.apiKey = apiKey;
    }

    @Override
    public boolean authorize(long amount) {
        return amount > 0;
    }

    @Override
    public void run() {
        List<String> log = new ArrayList<>();
        log.add("ran");
    }
}
"""

RUBY_SRC = """\
require 'json'
require_relative 'helpers'

# Base gateway.
class BaseGateway
  def authorize(amount)
    raise NotImplementedError
  end
end

# Concrete gateway.
class StripeGateway < BaseGateway
  def initialize(api_key)
    @api_key = api_key
  end

  def authorize(amount, *rest, **opts)
    amount > 0
  end
end

def process_payment(amount, gateway = nil)
  gateway ||= StripeGateway.new('sk_test')
  gateway.authorize(amount)
end
"""

RUST_SRC = """\
use std::collections::HashMap;
use std::fmt::{self, Display};

/// A monetary amount.
#[derive(Debug, Clone)]
pub struct Money {
    pub amount: i64,
    pub currency: String,
}

/// Anything that can authorize a charge.
pub trait Gateway {
    fn authorize(&self, amount: i64) -> bool;
}

pub struct StripeGateway {
    pub api_key: String,
}

impl Gateway for StripeGateway {
    fn authorize(&self, amount: i64) -> bool {
        amount > 0
    }
}

impl Display for Money {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{} {}", self.currency, self.amount)
    }
}

pub fn process_payment(amount: i64, g: &dyn Gateway) -> bool {
    let mut seen: HashMap<String, i64> = HashMap::new();
    seen.insert("last".to_string(), amount);
    g.authorize(amount)
}
"""

# `requests` 2.19.1 has published advisories in the OSV database, so the CVE
# lookup has a real upstream answer to return rather than an empty list.
REQUIREMENTS = """\
requests==2.19.1
urllib3==1.24.1
flask==0.12.2
"""

CONFIG_WITH_SECRET = f'''\
"""Config with a deliberately FAKE credential for the secret scanner.

The key below is not and never was real — see fixtures.FAKE_AWS_KEY.
"""

AWS_ACCESS_KEY_ID = "{FAKE_AWS_KEY}"
AWS_SECRET_ACCESS_KEY = "{FAKE_AWS_SECRET}"
DATABASE_URL = "postgres://user:hunter2@localhost:5432/payments"
DEBUG = True
'''

# A real OWASP finding for the semgrep half of security_review. Verified
# against p/owasp-top-ten: shell=True on caller-supplied input trips
# `subprocess-shell-true` at ERROR severity. The hardcoded credential URL in
# config.py is NOT flagged by p/secrets, so relying on that alone left the
# semgrep path silently untested.
PY_ADMIN = '''\
"""Admin helpers. Contains a deliberate, documented vulnerability so the
self-test can prove semgrep is actually running (see fixtures.PY_ADMIN)."""
import subprocess


def run_maintenance_command(user_input):
    """Deliberately unsafe: shell=True on untrusted input (OWASP A03)."""
    return subprocess.run(user_input, shell=True, capture_output=True)
'''


CLAUDE_MD = """\
# Scratch Service

Two services live here: `svc_payments` and `svc_users`.

## Conventions

- All money is stored in minor units (integer cents).
- Every gateway must subclass `BaseGateway`.
"""

ADR_MD = """\
# 1. Use integer minor units for money

Date: 2026-01-15

## Status

Accepted

## Context

Floating point cannot represent decimal currency exactly.

## Decision

Store all monetary amounts as integer minor units.

## Consequences

Every boundary must convert explicitly.
"""


def build_scratch_repo(tmp: Path) -> Path:
    """Create and git-commit the full fixture repo. Returns its path."""
    repo = tmp / "scratch_repo"
    (repo / "svc_payments").mkdir(parents=True, exist_ok=True)
    (repo / "svc_users").mkdir(parents=True, exist_ok=True)
    (repo / "svc_payments" / "migrations").mkdir(parents=True, exist_ok=True)
    (repo / "tests").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    (repo / "web").mkdir(parents=True, exist_ok=True)

    (repo / "svc_payments" / "__init__.py").write_text("")
    (repo / "svc_payments" / "payments.py").write_text(PY_PAYMENTS)
    (repo / "svc_payments" / "routes.py").write_text(PY_ROUTES)
    (repo / "svc_payments" / "config.py").write_text(CONFIG_WITH_SECRET)
    (repo / "svc_payments" / "admin.py").write_text(PY_ADMIN)
    (repo / "svc_payments" / "gateway.go").write_text(GO_SRC)
    (repo / "svc_payments" / "Gateway.java").write_text(JAVA_SRC)
    (repo / "svc_payments" / "gateway.rb").write_text(RUBY_SRC)
    (repo / "svc_payments" / "gateway.rs").write_text(RUST_SRC)
    (repo / "svc_payments" / "migrations" / "001_add_currency.sql").write_text(MIGRATION_SQL)
    (repo / "svc_users" / "__init__.py").write_text("")
    (repo / "svc_users" / "users.py").write_text(PY_USERS)
    (repo / "web" / "cart.js").write_text(JS_SRC)
    (repo / "web" / "format.ts").write_text(TS_SRC)
    (repo / "tests" / "test_payments.py").write_text(PY_TEST)
    (repo / "requirements.txt").write_text(REQUIREMENTS)
    (repo / "CLAUDE.md").write_text(CLAUDE_MD)
    (repo / "docs" / "adr" / "0001-money-minor-units.md").write_text(ADR_MD)
    (repo / "openapi.yaml").write_text(OPENAPI_V1)
    (repo / "README.md").write_text("# Scratch\n\nFixture repo for the JSAT self-test.\n")

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: initial payments and users services")

    # A few more commits so incident investigation and recent-changes have a
    # real history to rank, with messages a keyword scorer can bite on.
    (repo / "svc_payments" / "payments.py").write_text(
        PY_PAYMENTS.replace('return {"refunded": payment_id}',
                            'return {"refunded": payment_id, "status": "ok"}')
    )
    _git(repo, "commit", "-qam", "fix: include status in refund response")

    (repo / "svc_users" / "users.py").write_text(
        PY_USERS + '\n\ndef delete_user(user_id):\n    return {"deleted": user_id}\n'
    )
    _git(repo, "commit", "-qam", "feat: add delete_user to the user service")

    (repo / "web" / "cart.js").write_text(JS_SRC + "\nexport const VERSION = '1.1.0';\n")
    _git(repo, "commit", "-qam", "chore: bump cart version")

    _git(repo, "tag", "v1")

    # The breaking spec change lands as its own commit so `git diff v1..HEAD`
    # over openapi.yaml is a genuine two-ref contract comparison.
    (repo / "openapi.yaml").write_text(OPENAPI_V2)
    _git(repo, "commit", "-qam",
         "feat!: drop /refunds and require currency on POST /payments")

    (repo / "svc_payments" / "payments.py").write_text(
        PY_PAYMENTS.replace("if amount <= 0:", "if amount < 0:")
    )
    _git(repo, "commit", "-qam",
         "fix: payment validation regression causing timeout errors in production")
    _git(repo, "tag", "v2")

    return repo


def scratch_facts() -> dict[str, object]:
    """Ground truth about the fixture repo, for assertions.

    Kept next to the builder so a fixture change that invalidates an
    assertion is a one-file edit rather than a hunt through the suites.
    """
    return {
        "languages": {"python", "javascript", "go", "java", "ruby", "rust"},
        "services": {"svc_payments", "svc_users", "web", "tests", "docs"},
        "functions_present": [
            "validate_amount", "charge_card", "process_payment",
            "handle_payment_request", "refund_payment", "get_user",
        ],
        "classes_present": ["StripeGateway", "BaseGateway", "InsufficientFunds"],
        "untested_function": "refund_payment",
        "tested_function": "process_payment",
        "call_chain": ["handle_payment_request", "process_payment",
                       "charge_card", "validate_amount"],
        "inherits": ("StripeGateway", "BaseGateway"),
        "fake_secret": FAKE_AWS_KEY,
        "semgrep_rule_substring": "subprocess-shell-true",
        "vulnerable_file": "svc_payments/admin.py",
        "cve_package": "requests",
        "removed_endpoint": "/refunds",
        "old_ref": "v1",
        "new_ref": "v2",
    }
