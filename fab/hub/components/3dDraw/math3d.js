"use strict";

/**
 * 3D math for a perspective canvas renderer with arcball rotation.
 *
 * Coordinate arrays are always [x, y, z].
 * Quaternions are [x, y, z, w].
 */

export function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(v, hi));
}

export function lerp(a, b, t) {
  return a + (b - a) * t;
}

function dot(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function cross(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function length(v) {
  return Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
}

function normalize(v) {
  const len = length(v);
  if (len < 1e-12) return [0, 0, 1];
  return [v[0] / len, v[1] / len, v[2] / len];
}

export function scale(v, s) {
  return [v[0] * s, v[1] * s, v[2] * s];
}

export function add(a, b) {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

function sub(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

// ---- Quaternions ----

export function quatFromAxisAngle(axis, angle) {
  const a = normalize(axis);
  const half = angle / 2;
  const s = Math.sin(half);
  return [a[0] * s, a[1] * s, a[2] * s, Math.cos(half)];
}

export function quatMultiply(q1, q2) {
  return [
    q1[3] * q2[0] + q1[0] * q2[3] + q1[1] * q2[2] - q1[2] * q2[1],
    q1[3] * q2[1] - q1[0] * q2[2] + q1[1] * q2[3] + q1[2] * q2[0],
    q1[3] * q2[2] + q1[0] * q2[1] - q1[1] * q2[0] + q1[2] * q2[3],
    q1[3] * q2[3] - q1[0] * q2[0] - q1[1] * q2[1] - q1[2] * q2[2],
  ];
}

export function quatConjugate(q) {
  return [-q[0], -q[1], -q[2], q[3]];
}

export function quatRotateVector(q, v) {
  // q * v_q * q^-1
  const qv = [q[3] * v[0] + q[1] * v[2] - q[2] * v[1],
              q[3] * v[1] + q[2] * v[0] - q[0] * v[2],
              q[3] * v[2] + q[0] * v[1] - q[1] * v[0]];
  const qw = -q[0] * v[0] - q[1] * v[1] - q[2] * v[2];
  const qc = quatConjugate(q);
  return [
    qv[0] * qc[3] + qc[0] * qw + qv[1] * qc[2] - qv[2] * qc[1],
    qv[1] * qc[3] + qc[1] * qw + qv[2] * qc[0] - qv[0] * qc[2],
    qv[2] * qc[3] + qc[2] * qw + qv[0] * qc[1] - qv[1] * qc[0],
  ];
}

// ---- Camera ----

/**
 * Build a perspective camera looking at the origin.
 *
 * @param {number[]} q - orientation quaternion (default looks from +z toward origin, up = +y).
 * @param {number} range - half-width of the world cube shown at zoom=1.
 */
export function makeCamera(q, range) {
  const distance = range * 3;
  const focalLength = range * 1.8;

  // Default camera: at (0,0,distance), looking down -z, up = +y.
  const pos = quatRotateVector(q, [0, 0, distance]);
  const viewDir = normalize(scale(pos, -1)); // from camera to origin
  const defaultUp = [0, 1, 0];
  const up = normalize(quatRotateVector(q, defaultUp));
  const right = normalize(cross(viewDir, up));
  const upOrtho = normalize(cross(right, viewDir));

  return { q, range, distance, focalLength, pos, viewDir, up: upOrtho, right };
}

export function cameraBasisFromAngles(theta, phi, range) {
  // Build a quaternion that rotates the default camera to (theta, phi).
  const qPhi = quatFromAxisAngle([1, 0, 0], phi - Math.PI / 2);
  const qTheta = quatFromAxisAngle([0, 0, 1], theta);
  return quatMultiply(qTheta, qPhi);
}

// ---- Projection ----

function screenScale(camera, width, height, zoom) {
  return zoom * Math.min(width, height) / (2 * camera.range);
}

export function projectPoint(p, camera, width, height, zoom) {
  const ray = sub(p, camera.pos);
  const denom = dot(ray, camera.viewDir);
  if (denom <= 1e-9) return null; // behind or on the image plane

  const t = camera.focalLength / denom;
  const hit = add(camera.pos, scale(ray, t));
  const toHit = sub(hit, add(camera.pos, scale(camera.viewDir, camera.focalLength)));

  const du = dot(toHit, camera.right);
  const dv = dot(toHit, camera.up);
  const pixelScale = screenScale(camera, width, height, zoom);

  return {
    x: width / 2 + du * pixelScale,
    y: height / 2 - dv * pixelScale,
    z: denom, // depth for sorting: larger = farther
    scale: pixelScale,
  };
}

export function screenToWorldPlane(sx, sy, camera, width, height, zoom, planeDepth) {
  const pixelScale = screenScale(camera, width, height, zoom);
  const depthScale = planeDepth / camera.focalLength;
  const du = (sx - width / 2) / pixelScale * depthScale;
  const dv = -(sy - height / 2) / pixelScale * depthScale;

  const planeCenter = add(camera.pos, scale(camera.viewDir, planeDepth));
  return add(planeCenter, add(scale(camera.right, du), scale(camera.up, dv)));
}

export function screenToSupportPlane(sx, sy, camera, width, height, zoom, supportDistance) {
  const pixelScale = screenScale(camera, width, height, zoom);
  // Plane is at distance supportDistance from origin toward the camera.
  // viewDir points from camera to origin, so -viewDir points from origin toward the camera.
  const planeCenter = scale(camera.viewDir, -supportDistance);
  const planeDepthFromCamera = camera.distance - supportDistance;
  const depthScale = planeDepthFromCamera / camera.focalLength;
  const du = (sx - width / 2) / pixelScale * depthScale;
  const dv = -(sy - height / 2) / pixelScale * depthScale;

  return add(planeCenter, add(scale(camera.right, du), scale(camera.up, dv)));
}

// ---- Arcball ----

/**
 * Map a screen point to a unit vector in camera space.
 */
export function screenToArcball(sx, sy, width, height) {
  const r = Math.min(width, height) / 2;
  let x = (sx - width / 2) / r;
  let y = -(sy - height / 2) / r;
  const r2 = x * x + y * y;

  if (r2 <= 1) {
    return [x, y, Math.sqrt(1 - r2)];
  }
  const len = Math.sqrt(r2);
  return [x / len, y / len, 0];
}

/**
 * Compute the quaternion rotation from vector a to vector b.
 */
export function rotationBetween(a, b) {
  const na = normalize(a);
  const nb = normalize(b);
  const axis = cross(na, nb);
  const axisLen = length(axis);
  const dotVal = clamp(dot(na, nb), -1, 1);

  if (axisLen < 1e-9) {
    // Parallel or opposite.
    if (dotVal > 0) return [0, 0, 0, 1];
    // 180-degree rotation: pick an orthogonal axis.
    const ortho = Math.abs(na[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
    const perp = normalize(cross(na, ortho));
    return quatFromAxisAngle(perp, Math.PI);
  }

  const angle = Math.acos(dotVal);
  return quatFromAxisAngle(axis, angle);
}

/**
 * Distance from a point p to the line segment a-b.
 */
export function pointSegmentDistance(p, a, b) {
  const ab = sub(b, a);
  const ab2 = dot(ab, ab);

  let t = 0;
  if (ab2 > 0) {
    const ap = sub(p, a);
    t = clamp(dot(ap, ab) / ab2, 0, 1);
  }

  const closest = add(a, scale(ab, t));
  return length(sub(p, closest));
}
