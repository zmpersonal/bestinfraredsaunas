# BestHomeInfraredSauna.com

An infrared-only home sauna specification lab built for GitHub Pages.

## What it does

- Home-fit finder based on room dimensions, electrical service, capacity and budget.
- Infrared-only product index. Traditional, steam, barrel and hybrid saunas are excluded.
- Source-linked EMF claims index.
- 120V/15A and 120V/20A electrical compatibility checker.
- Generated model pages and fit lists.
- Downloadable JSON + CSV data.
- Weekly catalog refresh from the InHouse Wellness infrared sauna collection.

## GitHub Pages setup

1. Upload the contents of this folder to the repository root, including `.github`.
2. Repository **Settings → Pages → Build and deployment → Source → GitHub Actions**.
3. Set the custom domain to `besthomeinfraredsauna.com`.
4. Point DNS to GitHub Pages.
5. Run **Actions → Update infrared sauna data and deploy → Run workflow** once.

No API key is required.

## Infrared-only rule

The updater starts from `https://inhousewellness.com/collections/infrared-saunas`, then applies an additional exclusion test to product title, type and tags. Products identified as **traditional**, **hybrid**, or **steam sauna** are rejected. The descriptive body is not used for negative filtering because a pure infrared model may legitimately compare itself with a traditional sauna in marketing copy.

## Data caution

EMF labels are reported as product/manufacturer terminology. They are not treated as standardized certifications. Numerical EMF values and measurement distance are stored only when the source states them.
