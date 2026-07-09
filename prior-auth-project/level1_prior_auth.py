# import os
# from dotenv import load_dotenv
# from openai import AzureOpenAI

# load_dotenv()

# # ---- DEBUG: confirm what values are being loaded ----
# print("ENDPOINT:", os.getenv("AZURE_OPENAI_ENDPOINT"))
# print("KEY starts with:", os.getenv("AZURE_OPENAI_API_KEY")[:5] if os.getenv("AZURE_OPENAI_API_KEY") else "MISSING")
# print("DEPLOYMENT:", os.getenv("AZURE_OPENAI_DEPLOYMENT"))
# print("API VERSION:", os.getenv("AZURE_OPENAI_API_VERSION"))
# print("------------------------------------------------")

# client = AzureOpenAI(
#     azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
#     api_key=os.getenv("AZURE_OPENAI_API_KEY"),
#     api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
# )

# deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# doctor_note = """
# Patient: 64F with severe right knee pain for 18 months.
# X-ray shows advanced osteoarthritis. Failed NSAIDs, physiotherapy, and intra-articular steroid injection.
# Orthopedic surgeon recommends total knee replacement.
# """

# policy_snippet = """
# Total knee replacement is medically necessary when severe osteoarthritis is documented,
# conservative therapy has failed for at least 3 months, and imaging confirms advanced joint degeneration.
# """

# prompt = f"""
# You are a prior authorization assistant. Read the doctor's note and the insurer policy below.

# DOCTOR NOTE:
# {doctor_note}

# INSURER POLICY:
# {policy_snippet}

# Do the following:
# 1. Extract: age, sex, diagnosis, failed treatments, imaging evidence, requested procedure
# 2. Suggest the most likely ICD-10 code for the diagnosis, with a confidence score (0 to 1)
# 3. State whether the case matches the insurer's policy criteria, and list which criteria are met or missing

# Respond in plain, clearly labeled sections.
# """

# response = client.chat.completions.create(
#     model=deployment,
#     messages=[{"role": "user", "content": prompt}],
#     temperature=0,
# )

# print(response.choices[0].message.content)
