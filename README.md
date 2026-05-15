### Front
  
cd C:\code\Seat-Hunter-back

pip install -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload


### Back
  
cd C:\code\Seat-Hunter\frontend

npm install

npm run dev
