import asyncio
import uvicorn
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware  # SỬA LỖI: Thêm dòng import này
from playwright.async_api import async_playwright

app = FastAPI()
shared_page = None 

# --- CẤU HÌNH CORS (Sửa lỗi 405 Method Not Allowed) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- HÀM HỖ TRỢ SELECT2 (GIỮ NGUYÊN LOGIC) ---
async def fill_select2(page, container_selector, search_text):
    try:
        await page.wait_for_selector(container_selector, state="visible", timeout=5000)
        await page.click(container_selector)
        search_input = ".select2-container--open input.select2-search__field"
        await page.wait_for_selector(search_input, state="visible", timeout=3000)
        await page.fill(search_input, search_text)
        await asyncio.sleep(0.5) 
        result_xpath = f"//li[contains(@class, 'select2-results__option') and (normalize-space(text())='{search_text}' or contains(.,'{search_text}'))]"
        await page.wait_for_selector(result_xpath, state="visible", timeout=3000)
        await page.click(result_xpath)
        try:
            await page.wait_for_selector(".select2-container--open", state="hidden", timeout=2000)
        except:
            await page.keyboard.press("Escape")
        print(f"   [+] Đã chọn Select2: {search_text}")
    except Exception as e:
        print(f"   [!] Lỗi chọn Select2 '{search_text}': {e}")
        await page.keyboard.press("Escape")

# --- QUY TRÌNH THIẾT LẬP (GIỮ NGUYÊN LOGIC) ---
async def select_dropdown_human(page, selector, label_text):
    try:
        print(f"   [+] Đang chọn: {label_text}")
        await page.wait_for_selector(f"{selector}:not([disabled])", timeout=15000)
        await page.select_option(selector, label=label_text)
        await page.dispatch_event(selector, "change")
        await asyncio.sleep(2) 
    except Exception as e:
        print(f"   [!] Lỗi khi chọn {label_text}: {e}")

async def auto_fill_location_and_open_form():
    global shared_page
    try:
        print("\n[BƯỚC 1] Thiết lập Cơ sở lưu trú...")
        await select_dropdown_human(shared_page, "select#accomStay_cboPROVINCE_ID", "Thành phố Cần Thơ")
        await select_dropdown_human(shared_page, "select#accomStay_cboADDRESS_ID", "Phường Long Tuyền")
        await select_dropdown_human(shared_page, "select#accomStay_cboACCOMMODATION_TYPE", "Nhà ngăn phòng cho thuê")
        await select_dropdown_human(shared_page, "select#accomStay_cboNAME", "NHÀ TRỌ TÂM AN 2")
        
        print("[BƯỚC 2] Mở form thêm người...")
        btn_add = "a#btnAddPersonLT" 
        await shared_page.wait_for_selector(btn_add, state="visible")
        await shared_page.click(btn_add)
        await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=10000)
        await asyncio.sleep(1)
        print("[OK] Sẵn sàng nhận dữ liệu khách.")
    except Exception as e:
        print(f"[LỖI] Thiết lập thất bại: {e}")

# --- ĐIỀN THÔNG TIN KHÁCH (GIỮ NGUYÊN LOGIC) ---
async def fill_guest_data(data):
    global shared_page
    if not shared_page: 
        print("[LỖI] Chưa kết nối được trình duyệt.")
        return
    try:
        print(f"\n--- Đang nhập liệu cho: {data.get('ho_ten')} ---")
        await shared_page.fill("input#guest_txtCITIZENNAME", data.get('ho_ten', '').upper())
        await shared_page.fill("input#guest_txtIDCARD_NUMBER", data.get('cccd', ''))

        dob = data.get('ngay_birth', data.get('ngay_sinh', ''))
        if dob:
            await shared_page.evaluate(f"""
                (dateVal) => {{
                    const el = document.getElementById('guest_txtDOB');
                    el.value = dateVal;
                    if (window.jQuery && jQuery(el).data('datepicker')) {{ jQuery(el).datepicker('update', dateVal); }}
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    el.blur();
                }}
            """, dob)

        await fill_select2(shared_page, "#select2-guest_cboGENDER_ID-container", data.get('gioi_tinh', 'Nam'))
        await fill_select2(shared_page, "#select2-guest_cboCOUNTRY-container", data.get('quoc_gia', 'Cộng hòa xã hội chủ nghĩa Việt Nam'))
        await fill_select2(shared_page, "#select2-guest_cboRDPROVINCE_ID-container", data.get('tinh', ''))
        await fill_select2(shared_page, "#select2-guest_cboRDADDRESS_ID-container", data.get('xa', ''))
        
        try:
            nationality = data.get('quoc_tich', 'Việt Nam')
            await shared_page.wait_for_selector("#guest_mulNATIONALITY", state="visible", timeout=5000)
            await shared_page.evaluate(f"""
                (nationality) => {{
                    const select = document.getElementById('guest_mulNATIONALITY');
                    if (select) {{
                        for (let option of select.options) {{
                            if (option.text.includes(nationality) || option.text === nationality) {{
                                option.selected = true; break;
                            }}
                        }}
                        select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }}
            """, nationality)
        except: pass

        await fill_select2(shared_page, "#select2-guest_cboETHNIC_ID-container", data.get('dan_toc', 'Kinh'))
        await fill_select2(shared_page, "#select2-guest_cboOCCUPATION-container", data.get('nghe_nghiep', 'Tự do'))
        await shared_page.fill("input#guest_txtROOM", data.get('so_phong', ''))
        await shared_page.fill("input#guest_txtPLACE_OF_WORK", data.get('noi_lam_viec', ''))
        await shared_page.fill("textarea#guest_txtREASON", data.get('ly_do', 'làm việc'))
        await shared_page.fill("textarea#guest_txtRDADDRESS", data.get('dia_chi_chi_tiet', ''))
        
        # Start date
        sd = data.get('thoi_gian_luu_tru', '')
        if sd:
            await shared_page.evaluate(f"""(v) => {{ 
                const el = document.getElementById('guest_txtSTART_DATE'); 
                el.value = v; el.dispatchEvent(new Event('change', {{ bubbles: true }})); 
            }}""", sd)

        # End date
        ed = data.get('luu_tru_den', '')
        if ed:
            await shared_page.evaluate(f"""(v) => {{ 
                const el = document.getElementById('guest_txtEND_DATE'); 
                el.value = v; el.dispatchEvent(new Event('change', {{ bubbles: true }})); 
            }}""", ed)

        await shared_page.focus("input#guest_txtCITIZENNAME")
        await shared_page.evaluate("document.activeElement.blur()")
        
        await shared_page.click("#btnSaveNLT")
        print(f"[THÀNH CÔNG] Đã lưu: {data.get('ho_ten')}")

        # TỰ ĐỘNG MỞ LẠI FORM (GIỮ NGUYÊN LOGIC)
        await asyncio.sleep(2) 
        await shared_page.click("a#btnAddPersonLT")
        await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=10000)
        await asyncio.sleep(1)

    except Exception as e:
        print(f"[LỖI] {e}")

# --- API (GIỮ NGUYÊN LOGIC) ---
@app.post("/send-to-web")
async def receive_data(data: dict, background_tasks: BackgroundTasks):
    if "items" in data and isinstance(data["items"], list):
        for item in data["items"]:
            background_tasks.add_task(fill_guest_data, item)
        return {"status": "processing", "message": f"Đang nhập {len(data['items'])} người."}
    background_tasks.add_task(fill_guest_data, data)
    return {"status": "processing", "message": f"Đang nhập {data.get('ho_ten')}"}

# --- REDIRECT (GIỮ NGUYÊN LOGIC) ---
async def check_url_and_redirect():
    global shared_page
    target_trigger = "https://dichvucong.bocongan.gov.vn/?home=1"
    cong_dan_url = "https://dichvucong.bocongan.gov.vn/dich-vu-cong/cong-dan"
    search_result_url = "https://dichvucong.bocongan.gov.vn/bocongan/bothutuc/listThuTuc?co_quan_cha=&loai_co_quan=&co_quan_con=&linh_vuc=&muc_do=&tukhoa=l%C6%B0u%20tr%C3%BA&doi_tuong=&cap_thuc_hien=&co_quan_cuc=&co_quan_tinh=&co_quan_huyen=&co_quan_xa="
    target_destination = "https://dichvucong.bocongan.gov.vn/bo-cong-an/tiep-nhan-online/chon-truong-hop-ho-so?ma-thu-tuc-public=26346"
    
    while True:
        try:
            if shared_page:
                current_url = shared_page.url
                if cong_dan_url in current_url:
                    await shared_page.goto(search_result_url)
                    await asyncio.sleep(2)
                elif target_trigger in current_url:
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
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            shared_page = context.pages[0] if context.pages else await context.new_page()
            
            print("[HỆ THỐNG] Đã kết nối Chrome.")
            await shared_page.goto("https://dichvucong.bocongan.gov.vn/")
            asyncio.create_task(check_url_and_redirect())
            
            config = uvicorn.Config(app, host="127.0.0.1", port=8000, loop="asyncio")
            server = uvicorn.Server(config)
            await server.serve()
        except Exception as e:
            print(f"[LỖI] {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass