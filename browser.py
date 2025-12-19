import asyncio
import uvicorn
from fastapi import FastAPI, BackgroundTasks
from playwright.async_api import async_playwright

app = FastAPI()
shared_page = None 

# --- HÀM HỖ TRỢ SELECT2 ---
# --- HÀM HỖ TRỢ SELECT2 CẬP NHẬT ---
async def fill_select2(page, container_selector, search_text):
    """Xử lý dropdown Select2: Click -> Gõ tìm kiếm -> Chọn kết quả -> Đóng dropdown"""
    try:
        # 1. Đợi và Click vào container của Select2
        await page.wait_for_selector(container_selector, state="visible", timeout=5000)
        await page.click(container_selector)
        
        # 2. Gõ nội dung vào ô input search của Select2 ĐANG MỞ
        # Dùng lớp .select2-container--open để đảm bảo chọn đúng ô input đang hiển thị
        search_input = ".select2-container--open input.select2-search__field"
        await page.wait_for_selector(search_input, state="visible", timeout=3000)
        await page.fill(search_input, search_text)
        await asyncio.sleep(0.5) # Đợi danh sách lọc kết quả
        
        # 3. Chọn kết quả khớp với text
        # Sử dụng normalize-space để loại bỏ khoảng trắng thừa trong HTML
        result_xpath = f"//li[contains(@class, 'select2-results__option') and (normalize-space(text())='{search_text}' or contains(.,'{search_text}'))]"
        await page.wait_for_selector(result_xpath, state="visible", timeout=3000)
        await page.click(result_xpath)
        
        # 4. QUAN TRỌNG: Đợi dropdown đóng hoàn toàn để không che khuất các trường khác
        try:
            await page.wait_for_selector(".select2-container--open", state="hidden", timeout=2000)
        except:
            # Nếu dropdown không tự đóng, nhấn Escape để đóng thủ công
            await page.keyboard.press("Escape")
            
        print(f"   [+] Đã chọn Select2: {search_text}")
    except Exception as e:
        print(f"   [!] Lỗi chọn Select2 '{search_text}': {e}")
        # Đóng dropdown nếu bị lỗi để không làm kẹt các bước sau
        await page.keyboard.press("Escape")
# --- QUY TRÌNH TỰ ĐỘNG THIẾT LẬP BAN ĐẦU ---
async def select_dropdown_human(page, selector, label_text):
    try:
        print(f"   [+] Đang chọn: {label_text}")
        await page.wait_for_selector(f"{selector}:not([disabled])", timeout=15000)
        await page.select_option(selector, label=label_text)
        await page.dispatch_event(selector, "change")
        await asyncio.sleep(2) # Đợi web load dữ liệu phụ thuộc (ví dụ: chọn Quận xong đợi load Phường)
    except Exception as e:
        print(f"   [!] Lỗi khi chọn {label_text}: {e}")

async def auto_fill_location_and_open_form():
    global shared_page
    try:
        print("\n[BƯỚC 1] Thiết lập Cơ sở lưu trú...")
        # Lưu ý: Thay đổi text cho đúng với dữ liệu thực tế trên web của bạn
        await select_dropdown_human(shared_page, "select#accomStay_cboPROVINCE_ID", "Thành phố Cần Thơ")
        await select_dropdown_human(shared_page, "select#accomStay_cboADDRESS_ID", "Phường Long Tuyền")
        await select_dropdown_human(shared_page, "select#accomStay_cboACCOMMODATION_TYPE", "Nhà ngăn phòng cho thuê")
        await select_dropdown_human(shared_page, "select#accomStay_cboNAME", "NHÀ TRỌ TÂM AN 2")
        
        print("[BƯỚC 2] Mở form thêm người...")
        btn_add = "a#btnAddPersonLT" 
        await shared_page.wait_for_selector(btn_add, state="visible")
        await shared_page.click(btn_add)
        
        # Chờ modal hiện lên
        await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=10000)
        await asyncio.sleep(1)
        print("[OK] Sẵn sàng nhận dữ liệu khách.")
    except Exception as e:
        print(f"[LỖI] Thiết lập thất bại: {e}")

# --- HÀM ĐIỀN CHI TIẾT THÔNG TIN KHÁCH ---
async def fill_guest_data(data):
    global shared_page
    if not shared_page: 
        print("[LỖI] Chưa kết nối được trình duyệt.")
        return
        
    try:
        print(f"\n--- Đang nhập liệu cho: {data.get('ho_ten')} ---")

        # 1. Họ và tên (Viết hoa)
        await shared_page.fill("input#guest_txtCITIZENNAME", data.get('ho_ten', '').upper())

        # 2. Số CCCD/ĐDCN
        await shared_page.fill("input#guest_txtIDCARD_NUMBER", data.get('cccd', ''))

        # 3. NGÀY SINH (Xử lý đặc biệt cho Datepicker)
        dob = data.get('ngay_birth', data.get('ngay_sinh', ''))
        if dob:
            # Sử dụng Javascript để gán giá trị và kích hoạt sự kiện của thư viện datepicker
            await shared_page.evaluate(f"""
                (dateVal) => {{
                    const el = document.getElementById('guest_txtDOB');
                    el.value = dateVal;
                    // Kích hoạt sự kiện của jQuery Datepicker nếu có
                    if (window.jQuery && jQuery(el).data('datepicker')) {{
                        jQuery(el).datepicker('update', dateVal);
                    }}
                    // Kích hoạt các sự kiện input/change để web nhận diện
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    el.blur();
                }}
            """, dob)
            print(f"   [+] Đã nhập ngày sinh: {dob}")

        # 4. Giới tính (Select2)
        await fill_select2(shared_page, "#select2-guest_cboGENDER_ID-container", data.get('gioi_tinh', 'Nam'))

        # 4.1. Dân tộc (Select2)


        # 5. Quốc gia nơi ở (Select2)
        await fill_select2(shared_page, "#select2-guest_cboCOUNTRY-container", data.get('quoc_gia', 'Cộng hòa xã hội chủ nghĩa Việt Nam'))

        await fill_select2(shared_page, "#select2-guest_cboRDPROVINCE_ID-container", data.get('tinh', ''))

        await fill_select2(shared_page, "#select2-guest_cboRDADDRESS_ID-container", data.get('xa', ''))
        # 5.1. Quốc tịch (Select multiple - guest_mulNATIONALITY)
        try:
            nationality = data.get('quoc_tich', 'Việt Nam')
            # Chờ select quốc tịch xuất hiện
            await shared_page.wait_for_selector("#guest_mulNATIONALITY", state="visible", timeout=5000)
            # Sử dụng JavaScript để chọn option theo text
            await shared_page.evaluate(f"""
                (nationality) => {{
                    const select = document.getElementById('guest_mulNATIONALITY');
                    if (select) {{
                        // Tìm option có text khớp
                        for (let option of select.options) {{
                            if (option.text.includes(nationality) || option.text === nationality) {{
                                option.selected = true;
                                break;
                            }}
                        }}
                        // Kích hoạt sự kiện change
                        select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }}
            """, nationality)
            print(f"   [+] Đã chọn quốc tịch: {nationality}")
        except Exception as e:
            print(f"   [!] Lỗi chọn quốc tịch: {e}")
        await fill_select2(shared_page, "#select2-guest_cboETHNIC_ID-container", data.get('dan_toc', 'Kinh'))
        # 6. Nghề nghiệp (Select2)
        await fill_select2(shared_page, "#select2-guest_cboOCCUPATION-container", data.get('nghe_nghiep', 'Tự do'))

        # 7. Số phòng
        await shared_page.fill("input#guest_txtROOM", data.get('so_phong', ''))

        await shared_page.fill("input#guest_txtPLACE_OF_WORK", data.get('noi_lam_viec', ''))

        # 8. Lý do lưu trú
        await shared_page.fill("textarea#guest_txtREASON", data.get('ly_do', 'làm việc'))

        await shared_page.fill("textarea#guest_txtRDADDRESS", data.get('dia_chi_chi_tiet', ''))
        
        dob = data.get('thoi_gian_luu_tru', '')
        if dob:
            # Sử dụng Javascript để gán giá trị và kích hoạt sự kiện của thư viện datepicker
            await shared_page.evaluate(f"""
                (dateVal) => {{
                    const el = document.getElementById('guest_txtSTART_DATE');
                    el.value = dateVal;
                    // Kích hoạt sự kiện của jQuery Datepicker nếu có
                    if (window.jQuery && jQuery(el).data('datepicker')) {{
                        jQuery(el).datepicker('update', dateVal);
                    }}
                    // Kích hoạt các sự kiện input/change để web nhận diện
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    el.blur();
                }}
            """, dob)

        dob = data.get('luu_tru_den', '')
        if dob:
            # Sử dụng Javascript để gán giá trị và kích hoạt sự kiện của thư viện datepicker
            await shared_page.evaluate(f"""
                (dateVal) => {{
                    const el = document.getElementById('guest_txtEND_DATE');
                    el.value = dateVal;
                    // Kích hoạt sự kiện của jQuery Datepicker nếu có
                    if (window.jQuery && jQuery(el).data('datepicker')) {{
                        jQuery(el).datepicker('update', dateVal);
                    }}
                    // Kích hoạt các sự kiện input/change để web nhận diện
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    el.blur();
                }}
            """, dob)
        # Kích hoạt validate form lần cuối bằng cách blur họ tên
        await shared_page.focus("input#guest_txtCITIZENNAME")
        await shared_page.evaluate("document.activeElement.blur()")
        
        print(f"[THÀNH CÔNG] Đã điền xong thông tin cho khách: {data.get('ho_ten')}")

        btn_addu = "#btnSaveNLT" 
        await shared_page.wait_for_selector(btn_addu, state="visible")
        await shared_page.click(btn_addu)

        # --- TỰ ĐỘNG MỞ LẠI FORM CHO KHÁCH TIẾP THEO ---
        await asyncio.sleep(2) # Đợi lưu xong và modal đóng
        print("[BƯỚC 2] Mở form thêm người...")
        btn_add = "a#btnAddPersonLT" 
        await shared_page.wait_for_selector(btn_add, state="visible")
        await shared_page.click(btn_add)
        
        # Chờ modal hiện lên
        await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=10000)
        await asyncio.sleep(1)
        print("[OK] Sẵn sàng nhận dữ liệu khách.")

    except Exception as e:
        print(f"[LỖI] Nhập liệu khách hàng thất bại: {e}")

# --- API & MONITORING ---
@app.post("/send-to-web")
async def receive_data(data: dict, background_tasks: BackgroundTasks):
    background_tasks.add_task(fill_guest_data, data)
    return {"status": "processing", "message": f"Đang nhập liệu cho {data.get('ho_ten')}"}

async def check_url_and_redirect():
    global shared_page
    # URL sau khi đăng nhập thành công
    target_trigger = "https://dichvucong.bocongan.gov.vn/?home=1"
    # URL cần phát hiện để chuyển hướng
    cong_dan_url = "https://dichvucong.bocongan.gov.vn/dich-vu-cong/cong-dan"
    # URL đích khi phát hiện cong-dan
    search_result_url = "https://dichvucong.bocongan.gov.vn/bocongan/bothutuc/listThuTuc?co_quan_cha=&loai_co_quan=&co_quan_con=&linh_vuc=&muc_do=&tukhoa=l%C6%B0u%20tr%C3%BA&doi_tuong=&cap_thuc_hien=&co_quan_cuc=&co_quan_tinh=&co_quan_huyen=&co_quan_xa="
    # URL trực tiếp vào form Khai báo tạm trú
    target_destination = "https://dichvucong.bocongan.gov.vn/bo-cong-an/tiep-nhan-online/chon-truong-hop-ho-so?ma-thu-tuc-public=26346"
    
    while True:
        try:
            if shared_page:
                current_url = shared_page.url
                # Kiểm tra nếu đang ở trang cong-dan thì chuyển sang trang tìm kiếm
                if cong_dan_url in current_url:
                    print("[HỆ THỐNG] Phát hiện trang công dân! Đang chuyển sang trang tìm kiếm...")
                    await shared_page.goto(search_result_url)
                    await shared_page.wait_for_load_state("networkidle")
                    await asyncio.sleep(2)
                # Kiểm tra đăng nhập thành công và chuyển tới form
                elif target_trigger in current_url:
                    print("[HỆ THỐNG] Đăng nhập thành công! Đang chuyển hướng tới form...")
                    await shared_page.goto(target_destination)
                    await shared_page.wait_for_load_state("networkidle")
                    await auto_fill_location_and_open_form()
                    break
        except: pass
        await asyncio.sleep(2)

async def main():
    global shared_page
    async with async_playwright() as p:
        try:
            # Kết nối vào Chrome đang mở sẵn (cần mở chrome với --remote-debugging-port=9222)
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            
            if browser.contexts:
                context = browser.contexts[0]
                shared_page = context.pages[0] if context.pages else await context.new_page()
            else:
                context = await browser.new_context()
                shared_page = await context.new_page()
            
            print("[HỆ THỐNG] Đã kết nối Chrome. Vui lòng thực hiện đăng nhập trên trình duyệt...")
            await shared_page.goto("https://dichvucong.bocongan.gov.vn/")
            
            # Chạy nền việc kiểm tra trạng thái đăng nhập
            asyncio.create_task(check_url_and_redirect())
            
            # Khởi chạy server API
            config = uvicorn.Config(app, host="127.0.0.1", port=8000, loop="asyncio")
            server = uvicorn.Server(config)
            await server.serve()
        except Exception as e:
            print(f"[LỖI] Không thể kết nối Chrome (Hãy kiểm tra port 9222): {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[DỪNG] Đã đóng chương trình.")