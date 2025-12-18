@echo off
echo Sending POST request...

curl -X POST http://127.0.0.1:8000/send-to-web ^
 -H "Content-Type: application/json" ^
 -d "curl -X POST http://127.0.0.1:8000/send-to-web -H "Content-Type: application/json" -d "{\"ho_ten\": \"Nguyễn Văn A\", \"cccd\": \"091234567890\", \"ngay_sinh\": \"20/10/1990\", \"gioi_tinh\": \"Nam\", \"quoc_tich\": \"Việt Nam\", \"nghe_nghiep\": \"Tự do\", \"so_phong\": \"P.201\", \"ly_do\": \"Đi làm việc\"}""

echo.
echo Done!
pause
