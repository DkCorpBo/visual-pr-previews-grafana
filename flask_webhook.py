from flask import Flask, jsonify, request, send_from_directory
import requests
import base64
import json
import os
import urllib3
import logging
import threading

# Configure dedicated logging file
logging.basicConfig(
    filename=r"app_debug.log",
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s'
)

app = Flask(__name__)

# ================= CONFIGURATION PLACEHOLDERS =================
# Replace these values with your server configuration
GITEA_API_URL = "https://YOUR_GITEA_SERVER:PORT/api/v1"
GITEA_TOKEN = "YOUR_GITEA_PERSONAL_ACCESS_TOKEN"
GRAFANA_SA_TOKEN = "YOUR_GRAFANA_SERVICE_ACCOUNT_TOKEN"
GRAFANA_URL = "https://YOUR_GRAFANA_SERVER:PORT"
FLASK_SERVER_URL = "https://YOUR_FLASK_SERVER_DOMAIN_OR_IP:5000"
PREVIEWS_DIR = r"C:\path\to\static\previews" # Path to store preview PNGs
TRACKED_FOLDER = "Dashboards/" # Folder in repository containing dashboards
# ==============================================================

# Disable SSL verification warnings for internal/self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

@app.route('/flask')
def home():
    return "Gitea-Grafana PR Visual Preview webhook is running!", 200

@app.route('/flask/previews/<filename>')
def serve_preview(filename):
    return send_from_directory(PREVIEWS_DIR, filename)

def process_gitea_webhook_async(payload, event_type, action):
    logging.info(f"Processing Gitea webhook in background: Event={event_type}, Action={action}")
    try:
        # Handle pull request events when opened or synchronized (updated)
        if event_type == 'pull_request' and action in ['opened', 'synchronized']:
            pr_num = payload.get('number')
            commit_sha = payload.get('pull_request', {}).get('head', {}).get('sha')
            owner = payload.get('repository', {}).get('owner', {}).get('username')
            repo_name = payload.get('repository', {}).get('name')
            
            logging.info(f"Processing PR #{pr_num}, commit {commit_sha} in {owner}/{repo_name}")
            
            # Step 1: Query Gitea API for the list of files modified in the PR
            files_url = f"{GITEA_API_URL}/repos/{owner}/{repo_name}/pulls/{pr_num}/files"
            gitea_headers = {'Authorization': f'token {GITEA_TOKEN}'}
            
            files_res = requests.get(files_url, headers=gitea_headers, verify=False, timeout=10)
            if files_res.status_code != 200:
                logging.error(f"Error getting PR files from Gitea: {files_res.status_code} - {files_res.text}")
                return
                
            files_data = files_res.json()
            modified_dashboards = []
            
            for file_entry in files_data:
                filename = file_entry.get('filename', '')
                # Sincronizar solo archivos JSON dentro de la ruta especificada
                if filename.startswith(TRACKED_FOLDER) and filename.endswith('.json'):
                    modified_dashboards.append(filename)
                    
            logging.info(f"Modified dashboards found: {modified_dashboards}")
            
            if not modified_dashboards:
                logging.info("No modified dashboards in this PR. Skipping preview generation.")
                return
                
            # Step 2: Download each modified JSON file to get its UID and render it
            rendered_images_urls = []
            
            for filepath in modified_dashboards:
                content_url = f"{GITEA_API_URL}/repos/{owner}/{repo_name}/contents/{filepath}?ref={commit_sha}"
                content_res = requests.get(content_url, headers=gitea_headers, verify=False, timeout=10)
                if content_res.status_code != 200:
                    logging.error(f"Error getting file content for {filepath}: {content_res.status_code}")
                    continue
                    
                file_info = content_res.json()
                content_base64 = file_info.get('content', '')
                try:
                    content_str = base64.b64decode(content_base64).decode('utf-8')
                    dashboard_json = json.loads(content_str)
                    uid = dashboard_json.get('uid')
                    title = dashboard_json.get('title')
                    
                    # Fallback for Grafana API Server Custom Resource format (metadata.name is the UID)
                    if not uid:
                        metadata = dashboard_json.get('metadata', {})
                        uid = metadata.get('name')
                        
                    if not title:
                        spec = dashboard_json.get('spec', {})
                        title = spec.get('title', 'Dashboard')
                        
                    if uid:
                        logging.info(f"Rendering dashboard: {title} (UID: {uid})")
                        # Step 3: Render dashboard screenshot via Grafana Image Renderer
                        render_url = f"{GRAFANA_URL}/render/d/{uid}/?orgId=1&width=1200&height=800&kiosk"
                        grafana_headers = {'Authorization': f'Bearer {GRAFANA_SA_TOKEN}'}
                        
                        render_res = requests.get(render_url, headers=grafana_headers, verify=False, timeout=30)
                        
                        if render_res.status_code == 200:
                            # Save image locally
                            sanitized_filename = f"pr_{pr_num}_{uid}_{commit_sha[:7]}.png"
                            save_path = os.path.join(PREVIEWS_DIR, sanitized_filename)
                            with open(save_path, 'wb') as img_f:
                                img_f.write(render_res.content)
                            logging.info(f"Saved preview to {save_path}")
                            
                            # Build the URL to access this preview image
                            public_img_url = f"{FLASK_SERVER_URL}/flask/previews/{sanitized_filename}"
                            rendered_images_urls.append((title, public_img_url, uid))
                        else:
                            logging.error(f"Error rendering dashboard {uid} from Grafana: {render_res.status_code}")
                except Exception as ex:
                    logging.error(f"Exception processing dashboard {filepath}: {ex}")
                    
            if rendered_images_urls:
                # Step 4: Post comment back to the Gitea Pull Request
                comment_body = "### 📊 Vista Previa de Dashboards Modificados\n\n"
                comment_body += "Se han detectado cambios en los siguientes dashboards en este Pull Request:\n\n"
                
                for title, img_url, uid in rendered_images_urls:
                    comment_body += f"#### 📈 [{title}]({GRAFANA_URL}/d/{uid})\n"
                    comment_body += f"![{title}]({img_url})\n\n"
                    
                comment_body += "---\n*Comentario generado automáticamente por el servicio de automatización de Grafana.*"
                
                comment_url = f"{GITEA_API_URL}/repos/{owner}/{repo_name}/issues/{pr_num}/comments"
                comment_payload = {'body': comment_body}
                
                comment_res = requests.post(comment_url, headers=gitea_headers, json=comment_payload, verify=False, timeout=10)
                if comment_res.status_code == 201:
                    logging.info(f"Successfully posted preview comment to PR #{pr_num}")
                else:
                    logging.error(f"Error posting comment to Gitea PR: {comment_res.status_code} - {comment_res.text}")
            else:
                logging.info("No dashboards were successfully rendered.")
    except Exception as e:
        import traceback
        logging.error(f"Exception in background processing: {e}\n{traceback.format_exc()}")


@app.route('/flask/gitea-webhook', methods=['POST'])
def gitea_webhook():
    logging.info("Gitea webhook endpoint called")
    try:
        payload = request.json
        if not payload:
            logging.warning("Gitea webhook received empty payload")
            return jsonify({'error': 'No json payload'}), 400
            
        logging.info("Gitea Webhook payload received successfully")
        
        event_type = request.headers.get('X-Gitea-Event', '')
        action = payload.get('action')
        
        # Start background thread to process
        threading.Thread(
            target=process_gitea_webhook_async,
            args=(payload, event_type, action),
            daemon=True
        ).start()
        
        return jsonify({'status': 'accepted', 'message': 'Processing in background'}), 202
        
    except Exception as e:
        import traceback
        logging.error(f"Exception in gitea-webhook entry: {e}\n{traceback.format_exc()}")
        return 'Internal Server Error', 500


if __name__ == '__main__':
    # SSL Configuration (Provide paths to your local SSL certificates or run HTTP)
    app.run(
        host='0.0.0.0',
        port=5000,
        ssl_context=(
            'path/to/certificate.pem',
            'path/to/private.key'
        )
    )
