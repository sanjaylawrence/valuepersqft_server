import requests
from auth import get_access_token

TENANT = "valuepersqft"
BASE_URL = "https://connect.leadrat.com/api/v1/lead"

def main():
    token = get_access_token()
    headers = {"tenant": TENANT, "Authorization": f"Bearer {token}"}

    # First, a baseline call with no date filter at all, so we know the real totalCount
    baseline = requests.get(BASE_URL, headers=headers, params={"PageNumber": 1, "PageSize": 5})
    baseline_total = baseline.json().get("totalCount")
    print(f"BASELINE (no filter): status={baseline.status_code}, totalCount={baseline_total}")
    print()

    # Now try several common parameter name guesses
    test_date = "2026-09-16T00:00:00Z"

    guesses = [
        {"ModifiedSince": test_date},
        {"FromDate": test_date},
        {"LastModifiedFrom": test_date},
        {"UpdatedSince": test_date},
        {"ModifiedFrom": test_date},
        {"FromModifiedDate": test_date},
        {"StartDate": test_date},
    ]

    for guess in guesses:
        params = {"PageNumber": 1, "PageSize": 5, **guess}
        response = requests.get(BASE_URL, headers=headers, params=params)
        param_name = list(guess.keys())[0]
        total = None
        try:
            total = response.json().get("totalCount")
        except Exception:
            pass
        print(f"Tried '{param_name}': status={response.status_code}, totalCount={total}")

if __name__ == "__main__":
    main()