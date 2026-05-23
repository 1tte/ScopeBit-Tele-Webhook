<?php
/**
 * Webhook Receiver untuk Token Refresh ScopeBit Telegram
 * Menerima token yang terenkripsi Fernet, mendeskripsinya, dan mengekstrak Bearer token.
 */

header('Content-Type: application/json');

// 1. Kunci rahasia (Pastikan sama persis dengan WEBHOOK_SECRET di .env bot)
// Jika Anda mengubah ini di bot, Anda harus mengubahnya di sini juga.
$WEBHOOK_SECRET = "super_secret_webhook_key_123";

// 2. Fungsi dekripsi khusus Fernet untuk PHP
function fernet_decrypt($token_str, $secret) {
    // Menghasilkan 32-byte kunci (sama seperti di Python: hashlib.sha256(secret).digest())
    $key_bytes = hash('sha256', $secret, true);
    
    // Fernet membagi 32-byte menjadi 16-byte signing key dan 16-byte encryption key
    $signing_key = substr($key_bytes, 0, 16);
    $encryption_key = substr($key_bytes, 16, 16);
    
    // Mengembalikan URL-safe Base64 menjadi bentuk binary
    $token_bytes = base64_decode(strtr($token_str, '-_', '+/'));
    if (!$token_bytes) {
        return ['success' => false, 'error' => 'Invalid base64 encoding'];
    }
    
    // Memeriksa panjang minimum token (1 byte ver + 8 byte waktu + 16 byte IV + 32 byte HMAC)
    if (strlen($token_bytes) < 57) {
        return ['success' => false, 'error' => 'Token too short'];
    }
    
    // Mengekstrak bagian-bagian token
    $version = ord($token_bytes[0]);
    if ($version !== 0x80) {
        return ['success' => false, 'error' => 'Invalid Fernet version'];
    }
    
    $iv = substr($token_bytes, 9, 16);
    $ciphertext = substr($token_bytes, 25, -32);
    $hmac = substr($token_bytes, -32);
    
    // Validasi otentikasi (HMAC)
    $data_to_sign = substr($token_bytes, 0, -32);
    $calculated_hmac = hash_hmac('sha256', $data_to_sign, $signing_key, true);
    
    // Menggunakan hash_equals untuk mencegah serangan Timing Attack
    if (!hash_equals($calculated_hmac, $hmac)) {
        return ['success' => false, 'error' => 'HMAC authentication failed (Invalid Secret)'];
    }
    
    // Dekripsi menggunakan AES-128-CBC
    $decrypted = openssl_decrypt($ciphertext, 'aes-128-cbc', $encryption_key, OPENSSL_RAW_DATA, $iv);
    
    if ($decrypted === false) {
        return ['success' => false, 'error' => 'Decryption failed'];
    }
    
    return ['success' => true, 'data' => $decrypted];
}

// 3. Menangani Request POST
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'Method not allowed']);
    exit;
}

// Mengambil payload JSON mentah dari body request
$inputJSON = file_get_contents('php://input');
$input = json_decode($inputJSON, true);

if (!isset($input['data'])) {
    http_response_code(400);
    echo json_encode(['error' => 'No data provided']);
    exit;
}

$encrypted_data = $input['data'];

// 4. Dekripsi Payload
$result = fernet_decrypt($encrypted_data, $WEBHOOK_SECRET);

if (!$result['success']) {
    // Jika otentikasi gagal (contohnya secret salah), kembalikan HTTP 401
    http_response_code(401);
    echo json_encode(['error' => 'Unauthorized: ' . $result['error']]);
    exit;
}

// 5. Parse Data JSON hasil dekripsi
$payload = json_decode($result['data'], true);

if (!$payload || !isset($payload['access_token'])) {
    http_response_code(400);
    echo json_encode(['error' => 'Invalid payload format']);
    exit;
}

// Data berhasil diekstrak dengan aman!
$access_token = $payload['access_token'];
$refresh_token = $payload['refresh_token'];
$expired_at = $payload['expired_at'];
$timestamp = $payload['timestamp'];

// =========================================================
// MENYIMPAN TOKEN AGAR BISA DIGUNAKAN OLEH WEBSITE
// =========================================================

// Kita simpan ke file token.json
$token_data = [
    'access_token' => $access_token,
    'refresh_token' => $refresh_token,
    'expired_at' => $expired_at,
    'updated_at' => date('Y-m-d H:i:s')
];

// Menyimpan dalam format JSON yang rapi
file_put_contents('token.json', json_encode($token_data, JSON_PRETTY_PRINT));

// Mencatat log histori pembaruan (opsional)
$log_message = date('Y-m-d H:i:s') . " - Token Updated. Exp: $expired_at\n";
file_put_contents('token_update_log.txt', $log_message, FILE_APPEND);

// Berikan respon 200 OK ke Bot
http_response_code(200);
echo json_encode([
    'status' => 'success', 
    'message' => 'Token received and decrypted successfully'
]);
?>
