# Martech knowledge graph snapshot

- Generated: 2026-10-05T11:44:57Z
- Source files: martech-ontology.ttl, ecommerce-funnel-instances.ttl, login-journey-instances.ttl
- Triple count: 222

How to read this file:
1. Each section is one journey: requirement and KPI first, then its stages in order, then the components they use.
2. Caveats and owners are curated business context; quote them together with the component they describe.
3. Anything missing here may still be in the references/ files, so check there before saying it is not in the graph.

## Customer login journey

- Journey owner: Product Analytics
- Requirement: Understand monthly login frequency. Comment: We want to know how many logins we have monthly (MAU), and how that compares to overall sessions. Status: active.
- KPI: Monthly login rate. Formula: Monthly logins / Sessions. Target: 0.35. Owner: Product Analytics. Comment: Target: 35% of monthly sessions include a login (illustrative example, not a real commitment).

### Stages

1. Login. Measured by: Page name (dimension). Filter value: /customer/login. Rolls up to KPI: no.
2. Login success. Measured by: Page name (dimension). Filter value: /customer/login/success. Rolls up to KPI: yes.

### Components used by this journey

- Page name (dimension)
  - XDM path: web.webPageDetails.name
  - Refs URI: https://sandbox/SANDBOX_NAME/xdm/web.webPageDetails.name
  - Definition: The page name/path captured on each page view; used here to identify funnel steps by value.
  - Caveats: A shared, general-purpose dimension — filtering by value (e.g. /customer/login) is required to isolate a specific journey step. The raw component alone doesn't identify a stage.
  - Context: A general-purpose dimension, likely reused by other journeys in a real implementation — filtering by value is what distinguishes each specific use, not the component itself.
  - Owner: Digital Analytics
  - Data layer variables: digitalData.page.pageInfo.name

## Ecommerce purchase journey

- Journey owner: Digital Marketing
- Requirement: Understand shop performance and drop-off. Comment: We want to understand how our shop is performing, and where in the journey people drop off. Status: active.
- KPI: Order conversion rate. Formula: Orders / Product Views. Target: 0.0020. Owner: Ecommerce / Digital Marketing. Comment: Current value (2026): 0.11%. Target: 0.20% (illustrative example, not a real commitment).

### Stages

1. Product view. Measured by: Product views (metric). Filter value: none. Rolls up to KPI: no.
2. Cart add. Measured by: Product list adds (metric). Filter value: none. Rolls up to KPI: no.
3. Checkout. Measured by: Checkouts (metric). Filter value: none. Rolls up to KPI: no.
4. Order. Measured by: Orders (metric). Filter value: none. Rolls up to KPI: yes.

### Components used by this journey

- Checkouts (metric)
  - XDM path: commerce.checkouts.value
  - Refs URI: https://sandbox/SANDBOX_NAME/xdm/commerce.checkouts.value
  - Definition: Number of times a user started the checkout process.
  - Caveats: Counts checkout starts, not completions — a user can start checkout multiple times without purchasing.
  - Context: Marks the transition from browsing to transactional intent.
  - Owner: Digital Analytics
  - Data layer variables: digitalData.conversion.conversionFunnel.step
- Orders (metric)
  - XDM path: orders
  - Refs URI: https://sandbox/SANDBOX_NAME/xdm/orders
  - Definition: Number of completed purchase orders.
  - Caveats: Includes orders later cancelled or refunded — not net of returns.
  - Context: The funnel's terminal event and the numerator of the order conversion rate KPI.
  - Owner: Digital Analytics
  - Data layer variables: digitalData.conversion.conversionFunnel.step
- Product list adds (metric)
  - XDM path: commerce.productListAdds.value
  - Refs URI: https://sandbox/SANDBOX_NAME/xdm/commerce.productListAdds.value
  - Definition: Number of times a product was added to the cart.
  - Caveats: Does not deduplicate repeated adds of the same product within one session.
  - Context: First explicit purchase-intent signal in the funnel.
  - Owner: Digital Analytics
  - Data layer variables: digitalData.conversion.conversionFunnel.step
- Product views (metric)
  - XDM path: commerce.productViews.value
  - Refs URI: https://sandbox/SANDBOX_NAME/xdm/commerce.productViews.value
  - Definition: Number of times a product detail page was viewed.
  - Caveats: Counts page views, not unique visitors — a visitor viewing the same product twice counts twice.
  - Context: Entry point for the purchase funnel; used to benchmark top-of-funnel demand.
  - Owner: Digital Analytics
  - Data layer variables: digitalData.conversion.conversionFunnel.step
