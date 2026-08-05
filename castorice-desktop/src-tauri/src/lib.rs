use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use serde::{Deserialize, Serialize};
use tauri::Manager;

const BACKEND_PORT: u16 = 5477;
const READINESS_TIMEOUT_SECS: u64 = 120;
const HEALTH_CHECK_INTERVAL_SECS: u64 = 5;
const SIDECAR_NAME: &str = "castorice-backend";

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BackendStatus {
    running: bool,
    healthy: bool,
    port: u16,
}

struct BackendState {
    inner: Arc<BackendInner>,
}

struct BackendInner {
    process: Arc<Mutex<Option<Child>>>,
    project_root: std::path::PathBuf,
    stop_monitor: Arc<Mutex<bool>>,
    app_handle: Option<tauri::AppHandle>,
}

fn get_data_dir(app_handle: Option<&tauri::AppHandle>) -> PathBuf {
    if let Some(handle) = app_handle {
        if let Ok(dir) = handle.path().app_data_dir() {
            let _ = std::fs::create_dir_all(&dir);
            return dir;
        }
    }
    let dir = std::env::current_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join("castorice_data");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

fn spawn_backend(project_root: &Path, app_handle: Option<&tauri::AppHandle>) -> std::io::Result<Child> {
    let data_dir = get_data_dir(app_handle);

    // 优先尝试资源目录模式（打包后，后端在 resources/castorice-backend/ 下）
    if let Some(handle) = app_handle {
        if let Ok(resource_dir) = handle.path().resource_dir() {
            let exe_path = resource_dir.join("castorice-backend").join(format!("{}.exe", SIDECAR_NAME));
            if exe_path.exists() {
                eprintln!("[Castorice] 使用资源目录模式: {:?}", exe_path);
                return Command::new(&exe_path)
                    .args(["--mode", "http"])
                    .current_dir(&data_dir)
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn();
            }
        }
    }

    // 开发模式：使用系统 Python
    eprintln!("[Castorice] 使用开发模式 (Python)");
    Command::new("python")
        .args(["-m", "castorice.main", "--mode", "http"])
        .current_dir(project_root)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .or_else(|_| {
            Command::new("python3")
                .args(["-m", "castorice.main", "--mode", "http"])
                .current_dir(project_root)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
        })
}

fn check_backend_health(port: u16) -> bool {
    match TcpStream::connect_timeout(
        &format!("127.0.0.1:{}", port).parse().unwrap(),
        Duration::from_secs(2),
    ) {
        Ok(mut stream) => {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let _ = stream.write_all(b"GET /status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
            let mut buf = [0u8; 128];
            match stream.read(&mut buf) {
                Ok(n) if n > 0 => {
                    let resp = String::from_utf8_lossy(&buf[..n]);
                    resp.contains("200 OK")
                }
                _ => true,
            }
        }
        Err(_) => false,
    }
}

fn wait_for_backend_ready(port: u16, timeout_secs: u64) -> bool {
    let start = std::time::Instant::now();
    while start.elapsed().as_secs() < timeout_secs {
        if check_backend_health(port) {
            return true;
        }
        thread::sleep(Duration::from_millis(500));
    }
    false
}

fn is_process_alive(child: &mut Child) -> bool {
    match child.try_wait() {
        Ok(Some(_)) => false,
        Ok(None) => true,
        Err(_) => false,
    }
}

#[tauri::command]
fn start_backend(state: tauri::State<BackendState>) -> Result<BackendStatus, String> {
    let inner = &state.inner;
    let mut process_guard = inner.process.lock().map_err(|e| e.to_string())?;

    if let Some(ref mut child) = *process_guard {
        if is_process_alive(child) && check_backend_health(BACKEND_PORT) {
            return Ok(BackendStatus {
                running: true,
                healthy: true,
                port: BACKEND_PORT,
            });
        }
        let _ = child.kill();
        let _ = child.wait();
        *process_guard = None;
    }

    let app_handle = inner.app_handle.as_ref();
    let child = spawn_backend(&inner.project_root, app_handle)
        .map_err(|e| format!("启动后端失败: {}. 请确保已安装 Python 并安装了 castorice-agent 包。", e))?;

    *process_guard = Some(child);
    drop(process_guard);

    let ready = wait_for_backend_ready(BACKEND_PORT, READINESS_TIMEOUT_SECS);

    Ok(BackendStatus {
        running: true,
        healthy: ready,
        port: BACKEND_PORT,
    })
}

#[tauri::command]
fn stop_backend(state: tauri::State<BackendState>) -> Result<(), String> {
    let inner = &state.inner;

    let mut stop_guard = inner.stop_monitor.lock().map_err(|e| e.to_string())?;
    *stop_guard = true;
    drop(stop_guard);

    let mut process_guard = inner.process.lock().map_err(|e| e.to_string())?;
    if let Some(mut child) = process_guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    Ok(())
}

#[tauri::command]
fn get_backend_status(state: tauri::State<BackendState>) -> BackendStatus {
    let inner = &state.inner;
    let mut process_guard = match inner.process.lock() {
        Ok(g) => g,
        Err(_) => {
            return BackendStatus {
                running: false,
                healthy: false,
                port: BACKEND_PORT,
            }
        }
    };

    let alive = match *process_guard {
        Some(ref mut child) => is_process_alive(child),
        None => false,
    };

    let healthy = alive && check_backend_health(BACKEND_PORT);

    BackendStatus {
        running: alive,
        healthy,
        port: BACKEND_PORT,
    }
}

fn start_monitor(inner: Arc<BackendInner>) {
    let process = inner.process.clone();
    let project_root = inner.project_root.clone();
    let stop_flag = inner.stop_monitor.clone();
    let app_handle = inner.app_handle.clone();

    thread::spawn(move || loop {
        {
            let stop = stop_flag.lock().unwrap();
            if *stop {
                break;
            }
        }

        {
            let mut guard = match process.lock() {
                Ok(g) => g,
                Err(_) => {
                    thread::sleep(Duration::from_secs(HEALTH_CHECK_INTERVAL_SECS));
                    continue;
                }
            };

            let needs_restart = match *guard {
                Some(ref mut child) => {
                    let alive = is_process_alive(child);
                    if !alive {
                        let _ = child.wait();
                        true
                    } else {
                        false
                    }
                }
                None => false,
            };

            if needs_restart {
                eprintln!("[Castorice] 后端进程意外退出，正在重启...");
                let handle_ref = app_handle.as_ref();
                match spawn_backend(&project_root, handle_ref) {
                    Ok(new_child) => {
                        *guard = Some(new_child);
                        drop(guard);
                        if wait_for_backend_ready(BACKEND_PORT, READINESS_TIMEOUT_SECS) {
                            eprintln!("[Castorice] 后端已成功重启");
                        } else {
                            eprintln!("[Castorice] 后端重启超时");
                        }
                    }
                    Err(e) => {
                        eprintln!("[Castorice] 后端重启失败: {}", e);
                    }
                }
            }
        }

        thread::sleep(Duration::from_secs(HEALTH_CHECK_INTERVAL_SECS));
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let project_root = find_project_root();

    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .setup(move |app| {
            let app_handle = app.handle().clone();

            let inner = Arc::new(BackendInner {
                process: Arc::new(Mutex::new(None)),
                project_root: project_root.clone(),
                stop_monitor: Arc::new(Mutex::new(false)),
                app_handle: Some(app_handle.clone()),
            });

            let tauri_state = BackendState {
                inner: inner.clone(),
            };

            let monitor_inner = inner.clone();
            start_monitor(monitor_inner);

            let spawn_inner = inner.clone();
            let spawn_handle = app_handle.clone();
            thread::spawn(move || {
                let mut guard = spawn_inner.process.lock().unwrap();
                if guard.is_none() {
                    match spawn_backend(&spawn_inner.project_root, Some(&spawn_handle)) {
                        Ok(child) => {
                            *guard = Some(child);
                            drop(guard);
                            if wait_for_backend_ready(BACKEND_PORT, READINESS_TIMEOUT_SECS) {
                                eprintln!("[Castorice] 后端已就绪");
                            } else {
                                eprintln!("[Castorice] 后端启动超时");
                            }
                        }
                        Err(e) => {
                            eprintln!("[Castorice] 后端启动失败: {}", e);
                        }
                    }
                }
            });

            app.manage(tauri_state);

            #[cfg(desktop)]
            {
                use tauri_plugin_notification::NotificationExt;
                let _ = app
                    .notification()
                    .builder()
                    .title("Castorice 已启动")
                    .body("正在启动后端服务...")
                    .show();
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            start_backend,
            stop_backend,
            get_backend_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn find_project_root() -> std::path::PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::path::PathBuf::from("."));

    for candidate in &[
        exe_dir.join("../../.."),
        exe_dir.join("../.."),
        exe_dir.join(".."),
        std::path::PathBuf::from("../../.."),
        std::path::PathBuf::from("../.."),
    ] {
        let normalized = candidate.canonicalize().unwrap_or_else(|_| candidate.clone());
        if normalized.join("castorice").join("main.py").exists() {
            return normalized;
        }
    }

    std::env::current_dir()
        .ok()
        .and_then(|p| p.parent().map(|pp| pp.to_path_buf()))
        .unwrap_or_else(|| std::path::PathBuf::from("."))
}
