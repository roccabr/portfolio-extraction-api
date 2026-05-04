# Portfolio Extraction API

External API created to support the portfolio document processing flow used in n8n.

This API was created because some Python libraries required for PDF manipulation and data extraction could not be executed directly inside n8n.

## Overview

The API provides two main services:

1. Combine PDF pages side by side.
2. Extract portfolio information from a PDF and return it as a CSV file.

It is mainly used as an external processing layer between n8n, Lovable and other portfolio/report generation services.

## Base URL

```text
https://portfolio-extraction-api.vercel.app
