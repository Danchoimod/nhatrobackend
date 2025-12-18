    $body = @{

        ho_ten = "TRẦN PHÚ PHÀM"

        cccd = "087206008853"

        ngay_birth = "29/09/2006"

        gioi_tinh = "Nam"

        quoc_gia = "Cộng hòa xã hội chủ nghĩa Việt Nam"

        quoc_tich = "Việt Nam"

        dan_toc = "Kinh"

        noi_lam_viec = "Tự do"

        nghe_nghiep = "Tự do"

        so_phong = "C11"
        
        tinh = "Tỉnh Đồng Tháp"

        xa = "Xã Tân Long"
        
        ly_do = "Đi học"

        dia_chi_chi_tiet = "Ấp Tân Thạnh"

        luu_tru_den = "31/12/2025"

    } | ConvertTo-Json



    Invoke-RestMethod -Uri http://127.0.0.1:8000/send-to-web -Method Post -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body))