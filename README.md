# NEA Refuse Output & Waste System Advisor

VivATA office deployment for NEA COPEH refuse-output rates and related waste-infrastructure thresholds.

**Office calculator:** https://vivata-pte-ltd.github.io/nea-waste-advisor/

The software is independently developed by VivaTEQ Pte Ltd and is not affiliated with, approved by, or endorsed by NEA or any other Singapore authority. It is an informational design aid; QP review and project-specific authority confirmation remain necessary.

## Automatic standards workflow

1. The scheduled GitHub Action reads the official NEA practices page.
2. It discovers the highest editioned `copeh-YYYY.pdf` link on `www.nea.gov.sg`.
3. It downloads the PDF, verifies the origin and computes SHA-256.
4. PyMuPDF extracts Section 1.2 rates and the supported rules.
5. Strict validation rejects missing, ambiguous, conflicting, or out-of-range values.
6. Only a validated change replaces `standards.json` and the last-known-good PDF.
7. GitHub Pages redeploys; the calculator fetches and applies `standards.json` on every opening.

If extraction fails, the workflow fails and the published last-known-good manifest remains unchanged.

## Local verification

```bash
python -m pip install -r requirements.txt
python scripts/update_standards.py --force
python -m unittest discover -s tests -v
```

## Regulatory limitation

Automatic extraction can safely update recognized rates and rules. A structural rewrite of COPEH, renamed categories, or an ambiguous table causes a fail-closed result rather than guessing. QP review and project-specific authority confirmation remain necessary.

Repository operated by VivATA Pte Ltd for office use. Software © VivaTEQ Pte Ltd. All rights reserved.
