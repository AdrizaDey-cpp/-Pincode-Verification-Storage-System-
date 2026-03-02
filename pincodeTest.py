import requests

url = "https://api.postalpincode.in/pincode/700091"
r = requests.get(url)
print(r.status_code)
print(r.json())