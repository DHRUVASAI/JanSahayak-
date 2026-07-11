import pandas as pd
from train_nsap_model import generate_synthetic_data

print("Generating synthetic NSAP dataset...")
df = generate_synthetic_data(num_samples=5000)  # 5,000 samples is ideal for AutoAI demo
csv_path = "nsap_training_data.csv"
df.to_csv(csv_path, index=False)
print(f"Dataset successfully saved to {csv_path}!")
