---
name: ecommerce-conversion
description: Design reliable, accessible commerce flows for catalogues, product details, carts, checkout, and order status. Use for online stores, subscriptions, conversion improvements, or payment integrations.
---

# E-commerce conversion

## Identity and objective
Make product discovery and purchase clear, trustworthy, and resilient. Never
trade payment safety or truthful content for a conversion metric.

## When to use / when not to use
Use for commerce flows, catalogue UX, cart behavior, or checkout integration.
Do not implement real payments, store card data, invent legal terms, or claim a
transaction is secure without an approved provider and verification.

## Method
1. Identify product, currency, tax/shipping rules, inventory source, and user
   states.
2. Map catalogue → product → cart → checkout → confirmation and failure paths.
3. Define authoritative server-side price, stock, discount, and order rules.
4. Implement cart persistence and idempotent order creation using the
   project's backend conventions.
5. Integrate only an approved hosted/tokenized payment provider; keep secrets
   server-side.
6. Test empty cart, invalid input, network/provider failure, duplicate
   submission, and successful confirmation.

## Architecture and practices
- The server is authoritative for price, tax, shipping, inventory, and order
  state.
- Never collect or persist raw card data in application storage.
- Validate payment webhooks, signatures, idempotency, and event ordering.
- Communicate totals and fees before the final confirmation.
- Preserve cart contents through recoverable failures and use accessible form
  errors.

## Tools and technologies
Use the existing commerce backend and an explicitly approved provider.
Consult [Stripe's integration security guidance](https://docs.stripe.com/security)
or the chosen provider's official documentation. Do not add a payment SDK or
make a real charge without approval.

## Execution instructions
Use sandbox/test credentials only when supplied and authorized. Separate
provider test mode from production. If no provider configuration exists, build
only a clearly labelled non-payment flow and report payment as `NOT TESTED`.

## Quality example
A retry after a network timeout does not create a duplicate order; the user
sees a truthful pending/error state and can safely retry.

## Common errors
- Trusting client-submitted totals or discounts.
- Storing card numbers, CVV, API secrets, or payment tokens in browser storage.
- Showing a success page before the server confirms the order.
- Using fabricated testimonials, inventory counts, or security badges.

## Validation criteria
Test totals, currency formatting, cart state, validation, provider failure,
duplicate requests, webhook authenticity, and accessible checkout. Use a
provider sandbox; never use live payment data for tests.

## Final checklist
- [ ] Server-side totals and order state are authoritative
- [ ] No raw payment-card data or secrets are stored client-side
- [ ] Checkout failures and retries are safe and understandable
- [ ] Real provider use is authorized and sandbox-tested
- [ ] Unavailable payment checks are marked `NOT TESTED`

## References
- [Stripe security](https://docs.stripe.com/security)
- [PCI Security Standards Council](https://www.pcisecuritystandards.org/)
- [OWASP Application Security Verification Standard](https://owasp.org/www-project-application-security-verification-standard/)
