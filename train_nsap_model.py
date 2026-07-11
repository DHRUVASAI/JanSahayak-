import os
import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix

# Configuration
MODEL_PATH = "nsap_model.joblib"
DATA_SIZE = 12000
RANDOM_STATE = 42

def generate_synthetic_data(num_samples=DATA_SIZE):
    """
    Generates a synthetic dataset of applicants with demographic and socio-economic features,
    and assigns the correct NSAP scheme using the official eligibility rules.
    """
    np.random.seed(RANDOM_STATE)
    
    # 1. Randomly generate features
    age = np.random.randint(18, 90, size=num_samples)
    gender = np.random.choice([0, 1], size=num_samples, p=[0.5, 0.5])  # 0: Male, 1: Female
    is_bpl = np.random.choice([0, 1], size=num_samples, p=[0.4, 0.6])  # 60% BPL
    disability_percentage = np.random.randint(0, 100, size=num_samples)
    is_widow = np.random.choice([0, 1], size=num_samples, p=[0.8, 0.2])  # 20% Widows
    breadwinner_deceased = np.random.choice([0, 1], size=num_samples, p=[0.9, 0.1])  # 10% deceased breadwinner
    receiving_other_pension = np.random.choice([0, 1], size=num_samples, p=[0.7, 0.3])  # 30% receiving other pension

    # Ensure widows are female (widows in context of IGNWPS)
    is_widow = np.where(gender == 1, is_widow, 0)
    
    # 2. Apply deterministic rules to label the data
    labels = []
    for i in range(num_samples):
        # Non-BPL are completely ineligible for NSAP
        if is_bpl[i] == 0:
            labels.append("Ineligible")
            continue
            
        # IGNDPS: Indira Gandhi National Disability Pension Scheme
        # BPL, age 18-79, with severe/multiple disability (disability >= 80%)
        if 18 <= age[i] <= 79 and disability_percentage[i] >= 80:
            labels.append("IGNDPS")
            
        # NFBS: National Family Benefit Scheme
        # BPL, age 18-59, primary breadwinner deceased
        elif 18 <= age[i] <= 59 and breadwinner_deceased[i] == 1:
            labels.append("NFBS")
            
        # IGNWPS: Indira Gandhi National Widow Pension Scheme
        # BPL, widow, age 40-79
        elif gender[i] == 1 and is_widow[i] == 1 and 40 <= age[i] <= 79:
            labels.append("IGNWPS")
            
        # Annapurna Scheme
        # BPL, age >= 65, eligible for old age pension but not receiving it
        elif age[i] >= 65 and receiving_other_pension[i] == 0:
            labels.append("Annapurna")
            
        # IGNOAPS: Indira Gandhi National Old Age Pension Scheme
        # BPL, age >= 60
        elif age[i] >= 60:
            labels.append("IGNOAPS")
            
        else:
            labels.append("Ineligible")

    # Create DataFrame
    df = pd.DataFrame({
        'age': age,
        'gender': gender,
        'is_bpl': is_bpl,
        'disability_percentage': disability_percentage,
        'is_widow': is_widow,
        'breadwinner_deceased': breadwinner_deceased,
        'receiving_other_pension': receiving_other_pension,
        'scheme': labels
    })
    return df

def train_and_evaluate():
    print("--- Generating Synthetic NSAP Dataset ---")
    df = generate_synthetic_data()
    print(df['scheme'].value_counts())
    
    X = df.drop(columns=['scheme'])
    y = df['scheme']
    
    # Train-test split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=RANDOM_STATE)
    
    print("\n--- Training Random Forest Multi-Class Classifier ---")
    model = RandomForestClassifier(n_estimators=100, random_state=RANDOM_STATE)
    model.fit(X_train, y_train)
    
    # Predict
    y_pred = model.predict(X_test)
    
    # Evaluation
    acc = accuracy_score(y_test, y_pred)
    print(f"Model Accuracy: {acc:.4f}")
    
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    
    print("\nConfusion Matrix:")
    print(confusion_matrix(y_test, y_pred))
    
    # Save the model
    print(f"\nSaving model to {MODEL_PATH}...")
    joblib.dump(model, MODEL_PATH)
    print("Model saved successfully!")

if __name__ == "__main__":
    train_and_evaluate()
