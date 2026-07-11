import os
import logging
import joblib
import pandas as pd

logger = logging.getLogger(__name__)

_MODEL = None
# Path to the saved model file
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nsap_model.joblib")

def _load_model():
    global _MODEL
    if _MODEL is None:
        try:
            if os.path.exists(MODEL_PATH):
                _MODEL = joblib.load(MODEL_PATH)
                logger.info(f"NSAP Model loaded successfully from {MODEL_PATH}")
            else:
                logger.warning(f"NSAP Model not found at {MODEL_PATH}, using fallback rules.")
        except Exception as e:
            logger.error(f"Error loading NSAP model: {e}. Using fallback rules.")
    return _MODEL

def predict_nsap_scheme(age: int, gender: int, is_bpl: int, disability_percentage: int,
                         is_widow: int, breadwinner_deceased: int, receiving_other_pension: int) -> str:
    """
    Predicts the best fitting NSAP scheme using the trained classifier.
    If the model fails to load or predict, falls back to the deterministic eligibility rules.
    """
    model = _load_model()
    if model is not None:
        try:
            # Create a DataFrame matching the feature ordering
            df = pd.DataFrame([{
                'age': int(age),
                'gender': int(gender),
                'is_bpl': int(is_bpl),
                'disability_percentage': int(disability_percentage),
                'is_widow': int(is_widow),
                'breadwinner_deceased': int(breadwinner_deceased),
                'receiving_other_pension': int(receiving_other_pension)
            }])
            prediction = model.predict(df)[0]
            logger.info(f"NSAP model prediction: {prediction} for inputs: age={age}, gender={gender}, is_bpl={is_bpl}")
            return prediction
        except Exception as e:
            logger.error(f"Model prediction failed: {e}. Falling back to rules.")
            
    # Fallback deterministic rules
    if is_bpl == 0:
        return "Ineligible"
    if 18 <= age <= 79 and disability_percentage >= 80:
        return "IGNDPS"
    elif 18 <= age <= 59 and breadwinner_deceased == 1:
        return "NFBS"
    elif gender == 1 and is_widow == 1 and 40 <= age <= 79:
        return "IGNWPS"
    elif age >= 65 and receiving_other_pension == 0:
        return "Annapurna"
    elif age >= 60:
        return "IGNOAPS"
    return "Ineligible"

def extract_features_and_predict(conversation_history: list) -> str:
    """
    Parses conversation history to extract demographic/socio-economic inputs for the classifier.
    Runs the RandomForest classifier on extracted features.
    """
    import json
    import re
    from services import ai_provider

    transcript = ""
    for msg in conversation_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        transcript += f"{role.upper()}: {content}\n"

    prompt = f"Extract details from this conversation transcript:\n\n{transcript}"
    system = """You are a precise data extraction system. Analyze the transcript and return ONLY a valid JSON object matching this schema. If any field is not mentioned, use the defaults listed:
{
  "age": age as integer (default: 30),
  "gender": 1 if female/widow/woman/she, 0 if male/man/he (default: 0),
  "is_bpl": 1 if BPL/below poverty line/poor/low income/yes to bpl, 0 if not BPL/income above limit (default: 1),
  "disability_percentage": integer percentage (default: 0),
  "is_widow": 1 if widow/husband deceased, 0 if not (default: 0),
  "breadwinner_deceased": 1 if primary breadwinner died/passed away/deceased, 0 if not (default: 0),
  "receiving_other_pension": 1 if receiving other pension, 0 if not (default: 0)
}
Do not write any explanation, intro, markdown block format, or code blocks. Return ONLY the raw JSON."""

    try:
        raw = ai_provider.get_llm_response(prompt, system, max_tokens=150)
        logger.info(f"Raw feature extraction response: {raw}")
        raw = raw.replace("```json", "").replace("```", "").strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            raw = m.group(0)
        data = json.loads(raw)
        
        # Parse fields
        age = int(data.get("age", 30))
        gender = int(data.get("gender", 0))
        is_bpl = int(data.get("is_bpl", 1))
        disability_percentage = int(data.get("disability_percentage", 0))
        is_widow = int(data.get("is_widow", 0))
        breadwinner_deceased = int(data.get("breadwinner_deceased", 0))
        receiving_other_pension = int(data.get("receiving_other_pension", 0))

        # Predict
        return predict_nsap_scheme(
            age, gender, is_bpl, disability_percentage,
            is_widow, breadwinner_deceased, receiving_other_pension
        )
    except Exception as e:
        logger.error(f"Failed to extract features and predict NSAP: {e}")
        return "Ineligible"

