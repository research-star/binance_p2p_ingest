// Helpers de test: generan un keypair RSA self-signed, su JWKS, y mintean JWTs
// firmados — para simular el JWT que emite Cloudflare Access sin tocar la infra
// real. El test mockea el endpoint JWKS del team con este keypair (ver fetchMock
// en worker.test.js), así el verificador del Worker valida contra NUESTRA clave.

const enc = new TextEncoder();

function bytesToB64url(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = "";
  for (const x of b) bin += String.fromCharCode(x);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
const strToB64url = (s) => bytesToB64url(enc.encode(s));

export async function makeKeypairAndJwks(kid = "kid-1") {
  const pair = await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"]
  );
  const pub = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const jwk = { kty: pub.kty, n: pub.n, e: pub.e, alg: "RS256", use: "sig", kid };
  return { privateKey: pair.privateKey, jwks: { keys: [jwk] }, kid };
}

// Mintea un JWT RS256. Opciones para forzar casos negativos (aud/exp/kid/alg).
export async function mintJwt(
  privateKey,
  { kid, aud, iss, email, exp, nbf, iat, header } = {}
) {
  const now = Math.floor(Date.now() / 1000);
  const hdr = header || { alg: "RS256", kid, typ: "JWT" };
  const payload = { aud, iss, email, iat: iat ?? now, nbf: nbf ?? now - 30 };
  // exp === null → omitir el claim (para testear el rechazo "sin exp").
  if (exp !== null) payload.exp = exp ?? now + 3600;
  const signingInput = `${strToB64url(JSON.stringify(hdr))}.${strToB64url(
    JSON.stringify(payload)
  )}`;
  const sig = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    privateKey,
    enc.encode(signingInput)
  );
  return `${signingInput}.${bytesToB64url(sig)}`;
}
