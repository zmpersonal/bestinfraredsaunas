# BestHomeInfraredSauna.com — v2 retailer-link architecture

Static GitHub Pages site for comparing **infrared-only home saunas** by physical fit, electrical fit, spectrum and source-reported EMF claims.

## What changed in v2

- Individual model pages no longer link directly to ecommerce sites.
- Every model's **Where to Buy This Sauna** button stays internal and points to a retailer context page.
- `/retailers/inhouse-wellness/` contains the site's **single outbound link to InHouse Wellness**.
- Other retailer pages also contain a single outbound link per retailer.
- Model pages now show the actual product photo when the source feed/page exposes one, next to the dimension drawing.
- Additional infrared-only models from curated retailers are included below the featured InHouse catalog.
- Brands from additional retailers are deliberately sorted after all InHouse-sourced brands in the homepage dropdown.

## Current external comparison set

Configured in `data/external_models.json` and refreshable by the weekly updater:

- Clearlight — Sanctuary 2, Premier 2
- Health Mate — Enrich 2, Enrich 3
- HigherDOSE — Full Spectrum Infrared Sauna, 2-person variant
- Sunlighten — mPulse Believe

Edit `data/external_models.json` to add/remove external models or retailers. A retailer receives one internal context page and one outbound link.

## Product photos

The updater tries, in order:

1. Shopify product image data (InHouse feed)
2. OpenGraph image metadata from the product page
3. Product JSON-LD image metadata
4. Previously saved image URL

If no image is available, the model page shows a temporary photo placeholder. Run the Action after uploading so current product images are populated.

## Automatic update

Workflow: `.github/workflows/update-data.yml`

- manual via **Actions → Update infrared sauna data and deploy → Run workflow**
- scheduled Mondays at 09:23 UTC
- refreshes InHouse infrared products
- refreshes configured external product pages
- excludes traditional / hybrid / steam products from the InHouse feed
- rebuilds model, retailer, EMF, electrical and fit-list pages
- deploys the refreshed site in the same workflow

No API key is required.

## GitHub Pages setup

1. Upload all repository contents, including `.github`.
2. Settings → Pages → Source → **GitHub Actions**.
3. Set custom domain to `besthomeinfraredsauna.com`.
4. Run the update workflow once after upload.

## Outbound-link check

After a successful build, the generated HTML should contain exactly one `inhousewellness.com` anchor: the link on `/retailers/inhouse-wellness/` to the infrared sauna collection.
