# criticalflow-ai
CriticalFlow AI is an incident-intelligence system for IBM Z/LinuxONE environments. The system receives operational events or logs, detects abnormal behavior, identifies the incident, retrieves relevant operational knowledge, uses IBM Granite to explain the likely root cause with evidence, recommends a response, and shows the result in a dashboard.

## GitHub Repository Structure
```
CriticalFlowAI/
│
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── requirements.txt
├── pyproject.toml                  # if the team chooses a package-based setup
│
├── config/
│   └── settings.example.yaml
│
├── data/
│   ├── raw/
│   ├── processed/
│   ├── samples/
│   └── knowledge_base/
│
├── ibmz/
│   ├── README.md
│   ├── extract/
│   ├── parsers/
│   └── schemas/
│
├── ingestion/
│   ├── README.md
│   └── pipeline/
│
├── processing/
│   ├── cleaning.py
│   ├── validation.py
│   └── features.py
│
├── anomaly_detection/
│   ├── baseline.py
│   ├── model.py
│   ├── scoring.py
│   └── evaluation.py
│
├── rag/
│   ├── ingest.py
│   ├── retrieve.py
│   ├── prompts.py
│   └── knowledge_base.py
│
├── granite/
│   ├── client.py
│   ├── interface.py
│   └── fallback.py
│
├── api/
│   ├── main.py
│   ├── routes/
│   ├── schemas/
│   └── services/
│
├── dashboard/
│   ├── app.py
│   ├── components/
│   └── assets/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── end_to_end/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── data-contracts/
│   ├── demo/
│   └── team/
│
└── scripts/
    ├── seed_demo_data.py
    ├── run_pipeline.py
    └── health_check.py
```

## Git Branching Strategy
```
main
  └── dev
       ├── feature/ibmz
       ├── feature/data-pipeline
       ├── feature/anomaly
       ├── feature/rag-granite
       ├── feature/api-integration
       └── feature/dashboard
```
