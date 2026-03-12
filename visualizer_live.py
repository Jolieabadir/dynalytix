"""
Live video visualizer - plays pose data overlay without saving to disk.

Usage:
    python visualizer_live.py <video_path> <csv_path>
"""
import sys
import argparse
import csv
from pathlib import Path

import cv2 as cv
import numpy as np


class LiveVisualizer:
    """
    Live playback of pose data on video - no file saving.
    """
    
    # Skeleton connections (landmark pairs to draw lines between)
    SKELETON_CONNECTIONS = [
        # Torso
        ('left_shoulder', 'right_shoulder'),
        ('left_shoulder', 'left_hip'),
        ('right_shoulder', 'right_hip'),
        ('left_hip', 'right_hip'),
        # Left arm
        ('left_shoulder', 'left_elbow'),
        ('left_elbow', 'left_wrist'),
        # Right arm
        ('right_shoulder', 'right_elbow'),
        ('right_elbow', 'right_wrist'),
        # Left leg
        ('left_hip', 'left_knee'),
        ('left_knee', 'left_ankle'),
        ('left_ankle', 'left_heel'),
        # Right leg
        ('right_hip', 'right_knee'),
        ('right_knee', 'right_ankle'),
        ('right_ankle', 'right_heel'),
    ]
    
    # Angles to display on video
    DISPLAY_ANGLES = [
        'left_elbow',
        'right_elbow',
        'left_knee',
        'right_knee',
        'left_shoulder',
        'right_shoulder',
    ]
    
    # Colors (BGR format for OpenCV)
    COLOR_SKELETON = (0, 255, 0)      # Green
    COLOR_JOINTS = (0, 255, 255)       # Yellow
    COLOR_ANGLE_TEXT = (255, 255, 255) # White
    COLOR_SPEED_HIGH = (0, 0, 255)     # Red
    COLOR_SPEED_MED = (0, 165, 255)    # Orange
    COLOR_SPEED_LOW = (0, 255, 0)      # Green
    
    def __init__(self):
        """Initialize the visualizer."""
        self.frame_data = {}
        self.landmark_cols = []
        
    def load_csv(self, csv_path: Path) -> None:
        """
        Load frame data from CSV.
        
        Args:
            csv_path: Path to the CSV file with frame data
        """
        print(f"Loading data from: {csv_path}")
        
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            
            # Store all landmark column names
            fieldnames = reader.fieldnames
            self.landmark_cols = [col for col in fieldnames if col.startswith('landmark_')]
            
            for row in reader:
                frame_num = int(row['frame_number'])
                self.frame_data[frame_num] = row
        
        print(f"Loaded data for {len(self.frame_data)} frames")
    
    def play(
        self, 
        video_path: Path,
        show_skeleton: bool = True,
        show_angles: bool = True,
        show_speed: bool = True,
        playback_speed: float = 1.0
    ) -> None:
        """
        Play video with live overlay - no saving to disk.
        
        Args:
            video_path: Input video path
            show_skeleton: Whether to draw skeleton
            show_angles: Whether to show angle values
            show_speed: Whether to show speed indicator
            playback_speed: Playback speed multiplier (1.0 = normal, 2.0 = 2x speed)
        """
        cap = cv.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")
        
        # Get video properties
        fps = cap.get(cv.CAP_PROP_FPS)
        width = int(cap.get(cv.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv.CAP_PROP_FRAME_COUNT))
        
        print(f"\n🎬 Playing video: {video_path}")
        print(f"Resolution: {width}x{height}, FPS: {fps}, Frames: {total_frames}")
        print(f"Playback speed: {playback_speed}x")
        print("\nControls:")
        print("  SPACE - Pause/Resume")
        print("  Q - Quit")
        print("  → - Fast forward (skip 10 frames)")
        print("  ← - Rewind (go back 10 frames)")
        print()
        
        # Create window
        window_name = "Dynalytix Live Visualizer"
        cv.namedWindow(window_name, cv.WINDOW_NORMAL)
        
        # Calculate frame delay for proper playback speed
        frame_delay = int((1000 / fps) / playback_speed)
        
        frame_number = 0
        paused = False
        
        while True:
            if not paused:
                ret, frame = cap.read()
                if not ret:
                    print("\n✅ Video finished!")
                    break
                
                # Get frame data if available
                if frame_number in self.frame_data:
                    data = self.frame_data[frame_number]
                    
                    # Draw skeleton
                    if show_skeleton and self.landmark_cols:
                        self._draw_skeleton(frame, data)
                    
                    # Draw angles
                    if show_angles:
                        self._draw_angles(frame, data)
                    
                    # Draw speed indicator
                    if show_speed:
                        self._draw_speed(frame, data)
                
                # Draw frame number and controls hint
                cv.putText(
                    frame,
                    f"Frame: {frame_number}/{total_frames}",
                    (10, 30),
                    cv.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2
                )
                
                cv.putText(
                    frame,
                    "SPACE=Pause  Q=Quit  Arrows=Skip",
                    (10, height - 20),
                    cv.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1
                )
            
            # Show frame
            cv.imshow(window_name, frame)
            
            # Handle keyboard input
            key = cv.waitKey(frame_delay if not paused else 50) & 0xFF
            
            if key == ord('q') or key == 27:  # q or ESC
                print("\n⚠️  Playback stopped by user")
                break
            elif key == ord(' '):  # SPACE
                paused = not paused
                print("⏸️  Paused" if paused else "▶️  Playing")
            elif key == 83:  # Right arrow
                # Skip forward 10 frames
                frame_number = min(frame_number + 10, total_frames - 1)
                cap.set(cv.CAP_PROP_POS_FRAMES, frame_number)
                print(f"⏩ Skipped to frame {frame_number}")
            elif key == 81:  # Left arrow
                # Skip backward 10 frames
                frame_number = max(frame_number - 10, 0)
                cap.set(cv.CAP_PROP_POS_FRAMES, frame_number)
                print(f"⏪ Rewound to frame {frame_number}")
            
            if not paused:
                frame_number += 1
        
        cap.release()
        cv.destroyAllWindows()
    
    def _draw_skeleton(self, frame: np.ndarray, data: dict) -> None:
        """Draw skeleton lines on frame."""
        # Extract landmarks
        landmarks = {}
        for col in self.landmark_cols:
            if not col.endswith('_visibility'):
                # Parse landmark name from column (e.g., 'landmark_left_shoulder_x')
                parts = col.split('_')
                landmark_name = '_'.join(parts[1:-1])  # Remove 'landmark' prefix and axis suffix
                
                if landmark_name not in landmarks:
                    landmarks[landmark_name] = {}
                
                axis = parts[-1]  # 'x', 'y', 'z'
                value = data.get(col, '')
                
                if value and value != '':
                    landmarks[landmark_name][axis] = float(value)
        
        # Draw connections
        for point_a, point_b in self.SKELETON_CONNECTIONS:
            if point_a in landmarks and point_b in landmarks:
                a = landmarks[point_a]
                b = landmarks[point_b]
                
                if 'x' in a and 'y' in a and 'x' in b and 'y' in b:
                    pt1 = (int(a['x']), int(a['y']))
                    pt2 = (int(b['x']), int(b['y']))
                    cv.line(frame, pt1, pt2, self.COLOR_SKELETON, 2)
        
        # Draw joint circles
        for landmark_name, coords in landmarks.items():
            if 'x' in coords and 'y' in coords:
                pt = (int(coords['x']), int(coords['y']))
                cv.circle(frame, pt, 4, self.COLOR_JOINTS, -1)
    
    def _draw_angles(self, frame: np.ndarray, data: dict) -> None:
        """Draw angle values near joints."""
        # Position angles on the left side of the frame
        x_pos = 10
        y_start = 60
        y_offset = 25
        
        for i, angle_name in enumerate(self.DISPLAY_ANGLES):
            col_name = f'angle_{angle_name}'
            angle_value = data.get(col_name, '')
            
            if angle_value and angle_value != '':
                angle_deg = float(angle_value)
                text = f"{angle_name.replace('_', ' ').title()}: {angle_deg:.1f}°"
                
                y_pos = y_start + (i * y_offset)
                
                cv.putText(
                    frame,
                    text,
                    (x_pos, y_pos),
                    cv.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    self.COLOR_ANGLE_TEXT,
                    1
                )
    
    def _draw_speed(self, frame: np.ndarray, data: dict) -> None:
        """Draw speed indicator in top-right corner."""
        speed = data.get('speed_center_of_mass', '')
        
        if speed and speed != '':
            speed_val = float(speed)
            
            # Determine color based on speed
            if speed_val > 200:
                color = self.COLOR_SPEED_HIGH
                label = "HIGH"
            elif speed_val > 50:
                color = self.COLOR_SPEED_MED
                label = "MED"
            else:
                color = self.COLOR_SPEED_LOW
                label = "LOW"
            
            # Draw speed bar (top-right)
            height, width = frame.shape[:2]
            bar_width = 200
            bar_height = 30
            bar_x = width - bar_width - 10
            bar_y = 10
            
            # Background
            cv.rectangle(
                frame,
                (bar_x, bar_y),
                (bar_x + bar_width, bar_y + bar_height),
                (50, 50, 50),
                -1
            )
            
            # Speed fill (normalize to 0-300 px/s)
            fill_width = int((min(speed_val, 300) / 300) * bar_width)
            cv.rectangle(
                frame,
                (bar_x, bar_y),
                (bar_x + fill_width, bar_y + bar_height),
                color,
                -1
            )
            
            # Text
            text = f"{label}: {speed_val:.1f} px/s"
            cv.putText(
                frame,
                text,
                (bar_x + 5, bar_y + 20),
                cv.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1
            )


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Live playback of pose visualization (no disk saving).'
    )
    parser.add_argument(
        'video_path',
        type=str,
        help='Path to input video file'
    )
    parser.add_argument(
        'csv_path',
        type=str,
        help='Path to CSV file with frame data (must include landmarks)'
    )
    parser.add_argument(
        '--speed',
        type=float,
        default=1.0,
        help='Playback speed multiplier (default: 1.0, use 2.0 for 2x speed)'
    )
    parser.add_argument(
        '--no-skeleton',
        action='store_true',
        help='Do not draw skeleton'
    )
    parser.add_argument(
        '--no-angles',
        action='store_true',
        help='Do not show angle values'
    )
    parser.add_argument(
        '--no-speed',
        action='store_true',
        help='Do not show speed indicator'
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    video_path = Path(args.video_path)
    csv_path = Path(args.csv_path)
    
    # Check files exist
    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}")
        sys.exit(1)
    
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)
    
    # Create visualizer
    visualizer = LiveVisualizer()
    visualizer.load_csv(csv_path)
    
    # Play video
    visualizer.play(
        video_path,
        show_skeleton=not args.no_skeleton,
        show_angles=not args.no_angles,
        show_speed=not args.no_speed,
        playback_speed=args.speed
    )


if __name__ == '__main__':
    main()
