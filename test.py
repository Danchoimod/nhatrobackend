import asyncio
import uvicorn
import json
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

app = FastAPI()
shared_page = None 
data_queue = asyncio.Queue()
is_processing = False
selected_branch = "2"  # Mặc định chi nhánh 2

# Quản lý kết nối để gửi tín hiệu đổi màu
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except: pass

manager = ConnectionManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    # Khi có connection mới, tự động gửi QR nếu đang ở trang login
    asyncio.create_task(send_current_qr_to_new_client())
    
    try:
        while True: 
            message = await websocket.receive_text()
            # Xử lý message từ client
            try:
                data = json.loads(message)
                if data.get('action') == 'REQUEST_QR':
                    print("[WS] Frontend yêu cầu QR code mới")
                    # Gửi lại QR code nếu đang ở trang login
                    asyncio.create_task(resend_qr_code())
            except:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def fill_select2(page, container_selector, search_text):
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
    global shared_page, selected_branch
    try:
        print(f"\n[BƯỚC 1] Thiết lập Cơ sở lưu trú... (Chi nhánh {selected_branch})")
        await select_dropdown_human(shared_page, "select#accomStay_cboPROVINCE_ID", "Thành phố Cần Thơ")
        await select_dropdown_human(shared_page, "select#accomStay_cboADDRESS_ID", "Phường Long Tuyền")
        await select_dropdown_human(shared_page, "select#accomStay_cboACCOMMODATION_TYPE", "Nhà ngăn phòng cho thuê")
        
        # Chọn tên chi nhánh dựa trên selected_branch
        if selected_branch == "1":
            await select_dropdown_human(shared_page, "select#accomStay_cboNAME", "Hộ Kinh Doanh Nhà Trọ Tâm An 1")
            print("[OK] Đã chọn: Hộ Kinh Doanh Nhà Trọ Tâm An 1")
        else:  # Mặc định chi nhánh 2
            await select_dropdown_human(shared_page, "select#accomStay_cboNAME", "NHÀ TRỌ TÂM AN 2")
            print("[OK] Đã chọn: NHÀ TRỌ TÂM AN 2")
            
        # print("[BƯỚC 2] Mở form thêm người...")
        # btn_add = "a#btnAddPersonLT" 
        # await shared_page.wait_for_selector(btn_add, state="visible")
        # await shared_page.click(btn_add)
        # await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=10000)
        # await asyncio.sleep(1)
        # print("[OK] Sẵn sàng nhận dữ liệu khách.")
    except Exception as e:
        print(f"[LỖI] Thiết lập thất bại: {e}")

async def fill_guest_data(task_item):
    global shared_page
    data = task_item['data']
    idx = task_item['index']
    if not shared_page: return
    
    try:
        # Gửi tín hiệu đang xử lý dòng này
        await manager.broadcast({"type": "PROCESSING", "index": idx})
        
        print(f"\n--- Đang nhập liệu cho: {data.get('ho_ten')} ---")
        
        # Đảm bảo form đang mở trước khi điền - KIỂM TRA LỖI SỚM
        try:
            if not await shared_page.is_visible("#addpersonLT"):
                await shared_page.click("a#btnAddPersonLT")
                await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=5000)
        except Exception as form_err:
            raise Exception(f"Không thể mở form: {form_err}")

        # Điền thông tin cơ bản - KIỂM TRA LỖI NGAY
        try:
            await shared_page.fill("input#guest_txtCITIZENNAME", data.get('ho_ten', '').upper(), timeout=3000)
            await shared_page.fill("input#guest_txtIDCARD_NUMBER", data.get('cccd', ''), timeout=3000)
        except Exception as fill_err:
            raise Exception(f"Lỗi điền thông tin cơ bản: {fill_err}")

        dob = data.get('ngay_birth', data.get('ngay_sinh', ''))
        if dob:
            try:
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
            except Exception as dob_err:
                raise Exception(f"Lỗi điền ngày sinh: {dob_err}")

        # Điền select2 - KIỂM TRA LỖI NGAY
        try:
            await fill_select2(shared_page, "#select2-guest_cboGENDER_ID-container", data.get('gioi_tinh', ''))
            await fill_select2(shared_page, "#select2-guest_cboCOUNTRY-container", data.get('quoc_gia', 'Cộng hòa xã hội chủ nghĩa Việt Nam'))
            await fill_select2(shared_page, "#select2-guest_cboRDPROVINCE_ID-container", data.get('tinh', ''))
            await fill_select2(shared_page, "#select2-guest_cboRDADDRESS_ID-container", data.get('xa', ''))
        except Exception as select_err:
            raise Exception(f"Lỗi chọn dropdown: {select_err}")
        
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
        except Exception as nat_err:
            raise Exception(f"Lỗi chọn quốc tịch: {nat_err}")

        # Điền các select2 còn lại và thông tin khác
        try:
            await fill_select2(shared_page, "#select2-guest_cboETHNIC_ID-container", data.get('dan_toc', 'Kinh'))
            await fill_select2(shared_page, "#select2-guest_cboOCCUPATION-container", data.get('nghe_nghiep', 'Tự do'))
            await shared_page.fill("input#guest_txtROOM", data.get('so_phong', ''), timeout=3000)
            await shared_page.fill("input#guest_txtPLACE_OF_WORK", data.get('noi_lam_viec', ''), timeout=3000)
            await shared_page.fill("textarea#guest_txtREASON", data.get('ly_do', 'làm việc'), timeout=3000)
            await shared_page.fill("textarea#guest_txtRDADDRESS", data.get('dia_chi_chi_tiet', ''), timeout=3000)
        except Exception as fields_err:
            raise Exception(f"Lỗi điền thông tin bổ sung: {fields_err}")
        
        sd = data.get('thoi_gian_luu_tru', '')
        if sd: await shared_page.evaluate(f"document.getElementById('guest_txtSTART_DATE').value = '{sd}'")
        ed = data.get('luu_tru_den', '')
        if ed: await shared_page.evaluate(f"document.getElementById('guest_txtEND_DATE').value = '{ed}'")

        await shared_page.focus("input#guest_txtCITIZENNAME")
        await shared_page.evaluate("document.activeElement.blur()")
        
        # Click nút lưu - KIỂM TRA LỖI QUAN TRỌNG
        try:
            await shared_page.click("#btnSaveNLT", timeout=3000)
            print(f"[THÀNH CÔNG] Đã lưu: {data.get('ho_ten')}")
            # Thông báo hoàn thành để đổi màu xanh
            await manager.broadcast({"type": "COMPLETED", "index": idx})
        except Exception as save_err:
            raise Exception(f"Lỗi khi nhấn nút Lưu: {save_err}")

        await asyncio.sleep(2) 
        # Chuẩn bị cho người tiếp theo
        try:
            await shared_page.click("a#btnAddPersonLT", timeout=3000)
            await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=10000)
            await asyncio.sleep(1)
        except Exception as next_err:
            print(f"[CẢNH BÁO] Không mở được form tiếp theo: {next_err}")

    except Exception as e:
        # XỬ LÝ LỖI: Phát hiện sớm và dừng ngay, KHÔNG reset form
        await manager.broadcast({"type": "ERROR", "index": idx})
        print(f"\n[SKIP] Bỏ qua user #{idx+1} ({data.get('ho_ten', 'N/A')}): {str(e)}")
        print("   -> Chuyển sang user tiếp theo (dữ liệu cũ sẽ bị ghi đè)")
        # Không reset form, để user tiếp theo ghi đè lên

async def process_queue():
    global is_processing
    is_processing = True
    while not data_queue.empty():
        task_item = await data_queue.get()
        await fill_guest_data(task_item)
        data_queue.task_done()
    is_processing = False

@app.post("/send-to-web")
async def receive_data(data: dict, background_tasks: BackgroundTasks):
    global selected_branch
    items = data.get("items", [])
    branch = data.get("branch", "2")  # Mặc định chi nhánh 2
    selected_branch = branch
    
    for idx, item in enumerate(items):
        await data_queue.put({"index": idx, "data": item})
    if not is_processing: background_tasks.add_task(process_queue)
    return {"status": "started", "message": f"Bắt đầu xử lý {len(items)} người (Chi nhánh {branch})."}

@app.post("/set-branch")
async def set_branch(data: dict, background_tasks: BackgroundTasks):
    global selected_branch
    branch = data.get("branch", "2")
    selected_branch = branch
    print(f"\n[CHI NHÁNH] Đã chọn chi nhánh {branch}")
    
    # Thực hiện chọn lại cơ sở lưu trú
    background_tasks.add_task(auto_fill_location_and_open_form)
    
    return {"status": "success", "message": f"Đã chuyển sang chi nhánh {branch}"}

async def extract_qr_code(start_monitor=True):
    """Trích xuất mã QR từ trang đăng nhập và gửi về frontend"""
    global shared_page
    try:
        # Đợi QR code xuất hiện (có thể trong iframe hoặc div)
        await asyncio.sleep(3)  # Đợi QR load
        
        # Tìm ảnh QR - thử nhiều selector
        qr_selectors = [
            "img[alt='qr_images']",
            "img[src*='data:image']",
            "canvas",  # Một số trang vẽ QR bằng canvas
            ".qr-code img",
            "#qrcode img"
        ]
        
        qr_image_base64 = None
        for selector in qr_selectors:
            try:
                element = await shared_page.wait_for_selector(selector, timeout=5000)
                if element:
                    # Lấy base64 của ảnh
                    qr_image_base64 = await shared_page.evaluate("""
                        (selector) => {
                            const el = document.querySelector(selector);
                            if (el && el.tagName === 'IMG') {
                                return el.src;
                            } else if (el && el.tagName === 'CANVAS') {
                                return el.toDataURL();
                            }
                            return null;
                        }
                    """, selector)
                    
                    if qr_image_base64:
                        print(f"[QR CODE] Đã tìm thấy QR bằng selector: {selector}")
                        break
            except:
                continue
        
        if qr_image_base64:
            # Gửi QR code về frontend qua WebSocket
            await manager.broadcast({
                "type": "QR_CODE",
                "data": qr_image_base64
            })
            print("[QR CODE] Đã gửi QR code về frontend")
            
            # Chỉ bắt đầu theo dõi nếu được yêu cầu (tránh tạo nhiều monitor task)
            if start_monitor:
                asyncio.create_task(monitor_qr_expiration())
            
            return True
        else:
            print("[QR CODE] Không tìm thấy QR code")
            return False
            
    except Exception as e:
        print(f"[LỖI QR] {e}")
        return False

async def send_current_qr_to_new_client():
    """Gửi QR code hiện tại cho client mới kết nối (khi refresh page)"""
    global shared_page
    try:
        if not shared_page:
            return
        
        # Đợi 500ms để client sẵn sàng nhận
        await asyncio.sleep(0.5)
        
        current_url = shared_page.url
        print(f"[NEW CLIENT] Client mới kết nối, URL hiện tại: {current_url}")
        
        if "portal/p/home/thong-bao-luu-tru.html?ma_thu_tuc=2.001159" in current_url:
            print("vailone")
            await manager.broadcast({"type": "LOGIN_SUCCESS"})
            return
        # Kiểm tra xem có đang ở trang login không (cả trang chính và trang VNeID SSO)
        if "dichvucong.bocongan.gov.vn" in current_url or "sso.dancuquocgia.gov.vn" in current_url:
            # Kiểm tra xem đã đăng nhập chưa (kiểm tra cả URL và element)
            try:
                # Nếu đã vào trang công dân - chứng tỏ đã auth thành công
                if "portal/p/home/thong-bao-luu-tru.html?ma_thu_tuc=2.001159" in current_url:
                    print("[NEW CLIENT] Đã đăng nhập (tại trang công dân), gửi LOGIN_SUCCESS")
                    await manager.broadcast({"type": "LOGIN_SUCCESS"})
                    return    
                await shared_page.wait_for_selector("select#accomStay_cboPROVINCE_ID", timeout=1000)
                print("[NEW CLIENT] Đã đăng nhập, gửi LOGIN_SUCCESS")
                await manager.broadcast({"type": "LOGIN_SUCCESS"})
                return
            except:
                pass
            
            # Kiểm tra xem có QR code hiện tại không
            try:
                qr_selectors = [
                    "img[alt='qr_images']",
                    "img[src*='data:image']",
                    "canvas"
                ]
                
                qr_image_base64 = None
                for selector in qr_selectors:
                    try:
                        element = await shared_page.query_selector(selector)
                        if element and await element.is_visible():
                            qr_image_base64 = await shared_page.evaluate("""
                                (selector) => {
                                    const el = document.querySelector(selector);
                                    if (el && el.tagName === 'IMG') {
                                        return el.src;
                                    } else if (el && el.tagName === 'CANVAS') {
                                        return el.toDataURL();
                                    }
                                    return null;
                                }
                            """, selector)
                            
                            if qr_image_base64:
                                print(f"[NEW CLIENT] Tìm thấy QR hiện có, gửi cho client mới")
                                await manager.broadcast({
                                    "type": "QR_CODE",
                                    "data": qr_image_base64
                                })
                                
                                # Kiểm tra xem QR có hết hạn không (nút Tải lại có hiện không)
                                try:
                                    # Thử nhiều selector để tìm nút reload
                                    reload_selectors = [
                                        "button:has-text('Tải lại')",
                                        "button:has(svg#ic_refresh)",
                                        "button.bg-red100",
                                        "button[class*='red']",
                                        "//button[contains(., 'Tải lại')]"
                                    ]
                                    
                                    qr_is_expired = False
                                    for sel in reload_selectors:
                                        try:
                                            if sel.startswith('//'):
                                                reload_button = await shared_page.query_selector(f"xpath={sel}")
                                            else:
                                                reload_button = await shared_page.query_selector(sel)
                                            
                                            if reload_button and await reload_button.is_visible():
                                                qr_is_expired = True
                                                print(f"[NEW CLIENT] QR đã hết hạn (tìm thấy: {sel})")
                                                break
                                        except:
                                            continue
                                    
                                    if qr_is_expired:
                                        await manager.broadcast({"type": "QR_EXPIRED"})
                                except Exception as exp_err:
                                    print(f"[NEW CLIENT] Lỗi kiểm tra QR expiration: {exp_err}")
                                
                                return
                    except:
                        continue
                
                print("[NEW CLIENT] Không tìm thấy QR hiện có")
                
            except Exception as e:
                print(f"[NEW CLIENT] Lỗi khi kiểm tra QR: {e}")
                
    except Exception as e:
        print(f"[NEW CLIENT ERROR] {e}")

async def monitor_qr_expiration():
    """Theo dõi nút reload xuất hiện khi QR hết hạn và tự động click"""
    global shared_page
    try:
        print("[QR MONITOR] Bắt đầu theo dõi QR expiration...")
        
        # Các selector cho nút "Tải lại" trên website
        reload_button_selectors = [
            "button:has-text('Tải lại')",
            "button:has(svg#ic_refresh)",
            "button.bg-red100"
        ]
        
        # Đợi nút reload xuất hiện (timeout 5 phút)
        try:
            reload_button = None
            for selector in reload_button_selectors:
                try:
                    reload_button = await shared_page.wait_for_selector(selector, state="visible", timeout=300000)
                    if reload_button:
                        print(f"[QR MONITOR] ⚠️ QR đã hết hạn, nút Tải lại xuất hiện (selector: {selector})")
                        break
                except:
                    continue
            
            if reload_button:
                # Thông báo frontend QR đã hết hạn
                await manager.broadcast({
                    "type": "QR_EXPIRED"
                })
                
                # Tự động click nút "Tải lại" sau 2 giây
                await asyncio.sleep(2)
                print("[QR MONITOR] 🔄 Tự động click nút 'Tải lại' trên website...")
                await reload_button.click()
                await asyncio.sleep(3)  # Đợi QR mới load
                
                # Trích xuất QR code mới (không start monitor mới vì đang trong monitor)
                print("[QR MONITOR] Đang trích xuất QR code mới...")
                await extract_qr_code(start_monitor=False)
                
                # Tiếp tục monitor cho QR mới
                asyncio.create_task(monitor_qr_expiration())
            
        except Exception as timeout_err:
            # Nếu timeout hoặc đã đăng nhập trước khi hết hạn
            print("[QR MONITOR] Dừng theo dõi (đã đăng nhập hoặc timeout)")
            
    except Exception as e:
        print(f"[QR MONITOR ERROR] {e}")

async def resend_qr_code():
    """Lấy lại và gửi lại mã QR khi frontend yêu cầu"""
    global shared_page
    try:
        if not shared_page:
            print("[QR REFRESH] Shared page chưa khởi tạo")
            return
            
        current_url = shared_page.url
        print(f"[QR REFRESH] Frontend yêu cầu QR, URL hiện tại: {current_url}")
        
        # Kiểm tra xem có đang ở trang login không (cả trang chính và trang VNeID SSO)
        if "dichvucong.bocongan.gov.vn" in current_url or "sso.dancuquocgia.gov.vn" in current_url:
            # Kiểm tra xem đã đăng nhập chưa (kiểm tra cả URL và element)
            try:
                # Nếu đã vào trang công dân - chứng tỏ đã auth thành công
                if "dich-vu-cong/cong-dan" in current_url:
                    print("[QR REFRESH] Đã đăng nhập (tại trang công dân), không cần QR")
                    await manager.broadcast({"type": "LOGIN_SUCCESS"})
                    return
                    
                await shared_page.wait_for_selector("select#accomStay_cboPROVINCE_ID", timeout=2000)
                print("[QR REFRESH] Đã đăng nhập rồi, không cần QR")
                await manager.broadcast({"type": "LOGIN_SUCCESS"})
                return
            except:
                pass
            
            # BƯỚC 1: Kiểm tra xem có QR hiện tại không (chưa hết hạn)
            print("[QR REFRESH] Đang kiểm tra QR hiện tại...")
            qr_selectors = [
                "img[alt='qr_images']",
                "img[src*='data:image']",
                "canvas"
            ]
            
            qr_image_base64 = None
            qr_expired = False
            
            for selector in qr_selectors:
                try:
                    element = await shared_page.query_selector(selector)
                    if element and await element.is_visible():
                        qr_image_base64 = await shared_page.evaluate("""
                            (selector) => {
                                const el = document.querySelector(selector);
                                if (el && el.tagName === 'IMG') {
                                    return el.src;
                                } else if (el && el.tagName === 'CANVAS') {
                                    return el.toDataURL();
                                }
                                return null;
                            }
                        """, selector)
                        
                        if qr_image_base64:
                            print(f"[QR REFRESH] ✓ Tìm thấy QR hiện tại bằng selector: {selector}")
                            
                            # Kiểm tra xem QR có hết hạn không (tìm nút reload của VNeID)
                            try:
                                reload_selectors = [
                                    "button:has-text('Tải lại')",
                                    "button:has(svg#ic_refresh)",
                                    "button.bg-red100",
                                    "button[class*='red']",
                                    "//button[contains(., 'Tải lại')]"
                                ]
                                
                                for reload_sel in reload_selectors:
                                    try:
                                        if reload_sel.startswith('//'):
                                            reload_button = await shared_page.query_selector(f"xpath={reload_sel}")
                                        else:
                                            reload_button = await shared_page.query_selector(reload_sel)
                                        
                                        if reload_button and await reload_button.is_visible():
                                            qr_expired = True
                                            print(f"[QR REFRESH] ⚠️ QR đã hết hạn (nút reload: {reload_sel})")
                                            break
                                    except:
                                        continue
                                
                                if not qr_expired:
                                    print("[QR REFRESH] ✓ QR vẫn còn hợp lệ (không thấy nút reload)")
                            except Exception as exp_err:
                                print(f"[QR REFRESH] Lỗi kiểm tra expiration: {exp_err}")
                            
                            break
                except:
                    continue
            
            # BƯỚC 2: Nếu có QR và chưa hết hạn -> gửi lại QR hiện tại
            if qr_image_base64 and not qr_expired:
                print("[QR REFRESH] ✅ Gửi lại QR hiện tại (vẫn còn hợp lệ)")
                await manager.broadcast({
                    "type": "QR_CODE",
                    "data": qr_image_base64
                })
                return
            
            # BƯỚC 3: Nếu QR hết hạn hoặc không có QR -> click nút reload
            if qr_image_base64 and qr_expired:
                print("[QR REFRESH] 🔄 QR đã hết hạn, cần lấy QR mới...")
            elif not qr_image_base64:
                print("[QR REFRESH] ⚠️ KHÔNG TÌM THẤY QR hiện tại trên trang!")
                print(f"[QR REFRESH] URL hiện tại: {shared_page.url}")
            else:
                print("[QR REFRESH] 🔄 Cần tải QR mới...")
            
            # Tìm nút "Tải lại" trên website (khi QR hết hạn)
            reload_button_selectors = [
                "button:has-text('Tải lại')",
                "button:has(svg#ic_refresh)",
                "button.bg-red100",
                "//button[contains(., 'Tải lại')]"
            ]
            
            reload_button = None
            for selector in reload_button_selectors:
                try:
                    if selector.startswith("//"):
                        reload_button = await shared_page.wait_for_selector(f"xpath={selector}", timeout=2000)
                    else:
                        reload_button = await shared_page.wait_for_selector(selector, timeout=2000)
                    if reload_button and await reload_button.is_visible():
                        print(f"[QR REFRESH] Tìm thấy nút Tải lại: {selector}")
                        break
                except:
                    continue
            
            if reload_button:
                # Click nút "Tải lại" trên website
                print("[QR REFRESH] Đang click nút 'Tải lại' trên website...")
                await reload_button.click()
                await asyncio.sleep(3)
                
                # Trích xuất QR code mới
                await extract_qr_code(start_monitor=False)
            else:
                # Nếu không tìm thấy nút reload, thử reload trang
                print("[QR REFRESH] Không tìm thấy nút Tải lại, reload trang...")
                await shared_page.reload()
                await asyncio.sleep(2)
                
                # Tìm và click button đăng nhập lại
                login_button = await shared_page.wait_for_selector(
                    "div.login-IDP.BCA[onclick*='handleNoDomain']",
                    state="visible",
                    timeout=5000
                )
                if login_button:
                    await login_button.click()
                    await asyncio.sleep(2)
                    await extract_qr_code()
                        
    except Exception as e:
        print(f"[QR REFRESH ERROR] {e}")
                
    except Exception as e:
        print(f"[QR REFRESH ERROR] {e}")

async def wait_for_login_success():
    """Đợi đăng nhập thành công và thông báo cho frontend"""
    global shared_page
    try:
        print("[AUTH] Đang chờ người dùng quét QR và đăng nhập...")
        
        # Đợi URL thay đổi hoặc có dấu hiệu đăng nhập thành công
        target_url = "https://dichvucong.bocongan.gov.vn/bo-cong-an/tiep-nhan-online/chon-truong-hop-ho-so?ma-thu-tuc-public=26346"
        
        # Kiểm tra URL mỗi 2 giây
        for _ in range(60):  # Đợi tối đa 2 phút
            current_url = shared_page.url
            
            # Nếu đã vào trang công dân - chứng tỏ đã auth thành công NGAY LẬP TỨC
            if "dich-vu-cong/cong-dan" in current_url:
                print("[AUTH] ✅ Đã vào trang công dân - Đăng nhập thành công!")
                
                # Gửi thông báo đến frontend NGAY
                await manager.broadcast({
                    "type": "LOGIN_SUCCESS"
                })
                
                # Đợi 2 giây để frontend chuyển trang
                await asyncio.sleep(2)
                
                # Chuyển đến trang form và setup
                await shared_page.goto(target_url)
                await shared_page.wait_for_load_state("networkidle")
                await auto_fill_location_and_open_form()
                return True
            
            # Nếu URL chứa home=1 hoặc đã về trang đích
            if "home=1" in current_url or current_url == target_url:
                # Kiểm tra xem có element chứng tỏ đã đăng nhập không
                try:
                    # Tìm button hoặc element chỉ xuất hiện khi đã đăng nhập
                    await shared_page.wait_for_selector("select#accomStay_cboPROVINCE_ID", timeout=3000)
                    print("[AUTH] ✅ Đăng nhập thành công!")
                    
                    # Gửi thông báo đến frontend
                    await manager.broadcast({
                        "type": "LOGIN_SUCCESS"
                    })
                    
                    # Đợi 2 giây để frontend chuyển trang
                    await asyncio.sleep(2)
                    
                    # Setup form và sẵn sàng nhận data
                    await auto_fill_location_and_open_form()
                    return True
                except:
                    pass
            
            await asyncio.sleep(2)
        
        print("[AUTH] ⏱️ Timeout: Người dùng chưa đăng nhập trong 2 phút")
        return False
        
    except Exception as e:
        print(f"[AUTH ERROR] {e}")
        return False

async def check_url_and_redirect():
    global shared_page
    target_trigger = "https://dichvucong.bocongan.gov.vn/?home=1"
    cong_dan_url = "https://dichvucong.bocongan.gov.vn/dich-vu-cong/cong-dan"
    search_result_url = "https://dichvucong.bocongan.gov.vn/bocongan/bothutuc/listThuTuc?tukhoa=l%C6%B0u%20tr%C3%BA"
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

async def handle_qr_extraction():
    """Xử lý trích xuất QR code sau khi server đã sẵn sàng"""
    global shared_page
    try:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        shared_page = context.pages[0] if context.pages else await context.new_page()
        print("[HỆ THỐNG] Đã kết nối Chrome.")
        
        # Mở trang đăng nhập
        await shared_page.goto("https://dichvucong.bocongan.gov.vn/bo-cong-an/tiep-nhan-online/chon-truong-hop-ho-so?ma-thu-tuc-public=26346")
        await shared_page.wait_for_load_state("networkidle")
        
        # Kiểm tra xem đã đăng nhập chưa
        try:
            # Nếu đã đăng nhập sẽ thấy form này
            await shared_page.wait_for_selector("select#accomStay_cboPROVINCE_ID", timeout=3000)
            print("[AUTH] ✅ Đã đăng nhập rồi, bỏ qua bước QR")
            await manager.broadcast({"type": "LOGIN_SUCCESS"})
            await auto_fill_location_and_open_form()
            return
        except:
            print("[AUTH] Chưa đăng nhập, cần hiển thị QR")
        
        # Tìm và click button đăng nhập
        try:
            login_button = await shared_page.wait_for_selector(
                "div.login-IDP.BCA[onclick*='handleNoDomain']",
                state="visible",
                timeout=5000
            )
            if login_button:
                print("[AUTH] Tìm thấy button đăng nhập, đang click...")
                await login_button.click()
                await asyncio.sleep(2)
                
                # Đợi frontend kết nối WebSocket
                print("[AUTH] Đợi 3 giây để frontend kết nối...")
                await asyncio.sleep(3)
                
                # Trích xuất và gửi QR code
                qr_success = await extract_qr_code()
                
                if qr_success:
                    # Đợi người dùng quét QR và đăng nhập
                    await wait_for_login_success()
                else:
                    print("[AUTH] ❌ Không thể lấy QR code")
                
        except Exception as e:
            print(f"[AUTH] Không tìm thấy button đăng nhập: {e}")
            
    except Exception as e:
        print(f"[LỖI QR HANDLER] {e}")

async def main():
    global shared_page, p
    async with async_playwright() as playwright_instance:
        global p
        p = playwright_instance
        try:
            # Start WebSocket server trước
            config = uvicorn.Config(app, host="127.0.0.1", port=8000, loop="asyncio")
            server = uvicorn.Server(config)
            
            # Chạy QR extraction song song với server
            async def run_server_with_qr():
                # Đợi server khởi động
                await asyncio.sleep(1)
                print("[SERVER] WebSocket server đang chạy...")
                # Sau đó xử lý QR
                await handle_qr_extraction()
            
            # Chạy cả hai task cùng lúc
            await asyncio.gather(
                server.serve(),
                run_server_with_qr()
            )
        except Exception as e: 
            print(f"[LỖI] {e}")

if __name__ == "__main__":
    asyncio.run(main())