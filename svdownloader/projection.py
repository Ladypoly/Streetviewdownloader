"""
Equirectangular to rectilinear projection module.
Handles the mathematical conversion from 360 panoramic images to perspective tiles.
"""

import numpy as np
from PIL import Image


def create_rotation_matrix(yaw: float, pitch: float) -> np.ndarray:
    """
    Create a 3D rotation matrix using look-at construction.

    This ensures no roll - the camera's horizontal axis stays parallel
    to the ground plane (world XZ plane).

    Args:
        yaw: Horizontal rotation in radians (0 = +Z direction, positive = right)
        pitch: Vertical rotation in radians (0 = horizon, positive = up)

    Returns:
        3x3 rotation matrix that transforms camera rays to world rays
    """
    # Calculate the forward direction (where the camera looks)
    # Convert spherical (yaw, pitch) to Cartesian
    cos_pitch = np.cos(pitch)
    forward = np.array([
        np.sin(yaw) * cos_pitch,   # X
        np.sin(pitch),              # Y (up)
        np.cos(yaw) * cos_pitch    # Z
    ])

    # World up vector
    world_up = np.array([0.0, 1.0, 0.0])

    # Calculate right vector (must be horizontal, in XZ plane)
    # Right = world_up × forward (then normalize)
    right = np.cross(world_up, forward)
    right_norm = np.linalg.norm(right)

    if right_norm < 1e-6:
        # Looking straight up or down - forward is parallel to world_up
        # Use consistent right vector based on yaw
        right = np.array([np.cos(yaw), 0.0, -np.sin(yaw)])
    else:
        right = right / right_norm

    # Calculate camera up vector (perpendicular to forward and right)
    up = np.cross(forward, right)
    up = up / np.linalg.norm(up)

    # Build rotation matrix
    # Columns are where camera's X, Y, Z axes map to in world space
    # Camera: X=right, Y=up, Z=forward
    R = np.column_stack([right, up, forward])

    return R


def equirect_to_rectilinear(
    equirect_img: np.ndarray,
    yaw: float,
    pitch: float,
    fov: float,
    output_size: tuple[int, int]
) -> np.ndarray:
    """
    Extract a rectilinear (perspective) view from an equirectangular image.

    Uses inverse mapping: for each pixel in the output, compute the corresponding
    location in the equirectangular source image.

    Args:
        equirect_img: Source equirectangular image as numpy array (H, W, C)
        yaw: Horizontal look direction in radians (0 = center of image)
        pitch: Vertical look direction in radians (0 = horizon)
        fov: Field of view in radians
        output_size: (width, height) of output image

    Returns:
        Rectilinear image as numpy array
    """
    out_w, out_h = output_size
    eq_h, eq_w = equirect_img.shape[:2]

    # Focal length in pixels (pinhole camera model)
    f = (out_w / 2) / np.tan(fov / 2)

    # Create pixel coordinate grids for output image
    # Center the coordinates so (0,0) is at image center
    u = np.arange(out_w) - (out_w - 1) / 2
    v = np.arange(out_h) - (out_h - 1) / 2
    u, v = np.meshgrid(u, v)

    # Convert to 3D ray directions in camera space
    # Camera convention: X=right, Y=up, Z=forward
    # Screen convention: u=right, v=down
    # So we negate v to convert screen Y (down) to camera Y (up)
    x = u
    y = -v  # Flip Y: screen v-down -> camera Y-up
    z = np.full_like(u, f, dtype=np.float64)

    # Stack into (H, W, 3) array of ray directions
    rays = np.stack([x, y, z], axis=-1)

    # Normalize to unit vectors
    rays = rays / np.linalg.norm(rays, axis=-1, keepdims=True)

    # Apply rotation to transform rays to world space
    R = create_rotation_matrix(yaw, pitch)
    rays_world = rays @ R.T

    # Convert 3D rays to spherical coordinates (longitude, latitude)
    x_w = rays_world[..., 0]
    y_w = rays_world[..., 1]
    z_w = rays_world[..., 2]

    # Longitude: angle in XZ plane from Z axis
    lon = np.arctan2(x_w, z_w)

    # Latitude: angle from XZ plane
    lat = np.arcsin(np.clip(y_w, -1, 1))

    # Convert spherical to equirectangular pixel coordinates
    # Equirectangular: x spans [-pi, pi] -> [0, width]
    #                  y spans [pi/2, -pi/2] -> [0, height]
    eq_x = (lon / np.pi + 1) / 2 * eq_w
    eq_y = (0.5 - lat / np.pi) * eq_h

    # Wrap x coordinates for seamless horizontal tiling
    eq_x = eq_x % eq_w

    # Clamp y coordinates
    eq_y = np.clip(eq_y, 0, eq_h - 1)

    # Bilinear interpolation
    output = bilinear_sample(equirect_img, eq_x, eq_y)

    return output


def bilinear_sample(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """
    Sample from image using bilinear interpolation.

    Args:
        img: Source image (H, W, C)
        x: X coordinates to sample (any shape)
        y: Y coordinates to sample (same shape as x)

    Returns:
        Sampled values with same spatial shape as x/y
    """
    h, w = img.shape[:2]

    # Get integer and fractional parts
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = x0 + 1
    y1 = y0 + 1

    # Fractional parts for interpolation weights
    fx = x - x0
    fy = y - y0

    # Wrap x coordinates for seamless panorama
    x0 = x0 % w
    x1 = x1 % w

    # Clamp y coordinates
    y0 = np.clip(y0, 0, h - 1)
    y1 = np.clip(y1, 0, h - 1)

    # Sample four corners
    if img.ndim == 3:
        fx = fx[..., np.newaxis]
        fy = fy[..., np.newaxis]

    # Bilinear interpolation
    top = img[y0, x0] * (1 - fx) + img[y0, x1] * fx
    bottom = img[y1, x0] * (1 - fx) + img[y1, x1] * fx
    result = top * (1 - fy) + bottom * fy

    return result.astype(img.dtype)


def calculate_focal_length_mm(fov_rad: float, sensor_width_mm: float = 36.0) -> float:
    """
    Calculate equivalent focal length in mm for EXIF data.

    Assumes a standard 35mm full-frame sensor width.

    Args:
        fov_rad: Horizontal field of view in radians
        sensor_width_mm: Sensor width in mm (default 36mm for full-frame)

    Returns:
        Focal length in mm
    """
    return (sensor_width_mm / 2) / np.tan(fov_rad / 2)
