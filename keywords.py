# ─────────────────────────────────────────────────────────────────────────────
# ZINGG AI REDDIT AGENT — KEYWORDS & CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Search settings
RESULTS_PER_KEYWORD  = 3
BATCHES_PER_RUN      = 2
MAX_RESULTS_PER_RUN  = 10
MIN_RELEVANCE_SCORE  = 6

# Files (auto-created on first run)
SEEN_POSTS_FILE  = "seen_posts.csv"
BATCH_STATE_FILE = "batch_state.txt"

# About Zingg AI
PRODUCT_CONTEXT = """
Zingg AI is an open-source entity resolution and data deduplication framework
built for data engineers and data scientists.

WHAT IT DOES:
- Deduplicates large datasets using machine learning (no hand-crafted rules)
- Entity resolution: identifies that "John Smith, NYC" and "J. Smith, New York"
  are the same real-world person across different datasets
- Record linkage: connects records across multiple datasets referring to the same entity
- Works at scale with Apache Spark, Databricks, Snowflake, BigQuery, dbt
- Supports fuzzy matching, probabilistic matching, and ML-based matching

TARGET AUDIENCE:
- Data engineers building pipelines who face duplicate data problems
- Data scientists who need clean, deduplicated training data
- Companies building Customer 360, MDM, or identity graphs
- Anyone dealing with dirty data, duplicate records, or needing a single source of truth

ZINGG IS RELEVANT when someone is:
- Asking how to deduplicate data at scale
- Struggling with duplicate records in a database or pipeline
- Asking about entity resolution, record linkage, or fuzzy matching
- Building Customer 360, MDM, identity graph, or golden record
- Dealing with messy data quality issues in Spark, Databricks, Snowflake, dbt
- Looking for open-source alternatives to commercial data quality tools

ZINGG IS NOT RELEVANT when someone is:
- Asking about file/photo/music deduplication (backup software)
- Talking about duplicate discs, records (vinyl), games, or other non-data topics
- Asking something too generic with no connection to data engineering
"""

# All 15 keyword batches
ALL_BATCHES = {
    1:  ["entity resolution", "record linkage", "entity disambiguation",
         "entity matching", "fuzzy matching"],
    2:  ["data deduplication", "duplicate records", "merge purge",
         "probabilistic matching", "deterministic matching"],
    3:  ["identity resolution", "identity graph", "customer 360",
         "single customer view", "data unification"],
    4:  ["data quality", "dirty data", "garbage in garbage out",
         "data silos", "data matching"],
    5:  ["master data management", "single source of truth", "golden record",
         "data governance", "vendor master data"],
    6:  ["AI data quality", "training data quality", "data readiness AI",
         "AI agents data", "LLM data pipeline"],
    7:  ["dbt data quality", "dbt deduplication", "ELT data quality",
         "feature engineering duplicates", "data mastering"],
    8:  ["medallion architecture deduplication", "delta lake deduplication",
         "data lakehouse quality", "Spark entity resolution", "householding data"],
    9:  ["Snowflake deduplication", "Snowflake duplicate records",
         "BigQuery deduplication", "Snowpark Python data", "AWS Glue deduplication"],
    10: ["Databricks deduplication", "Databricks entity resolution",
         "Microsoft Fabric deduplication", "open source data quality",
         "Python deduplication library"],
    11: ["Martech", "Customer Data Platform CDP", "Composable CDP",
         "first-party data", "audience segmentation"],
    12: ["CRM duplicate contacts", "CRM data quality", "Salesforce duplicates",
         "HubSpot duplicate records", "data enrichment"],
    13: ["KYC data quality", "AML entity matching", "GDPR duplicate data",
         "HIPAA patient data deduplication", "financial crime data"],
    14: ["healthcare data quality", "patient identity resolution",
         "retail customer data unified", "fan 360 sports data", "duplicate customers"],
    15: ["open source machine learning data", "data engineering tools 2025",
         "supplier deduplication", "Zingg", "zingg.ai"],
}
