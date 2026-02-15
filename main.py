"""
Dynalytix - Climbing movement analysis.

Usage:
    python main.py <video_path> [--output <csv_path>] [--landmarks]
"""
import sys
import argparse
from pathlib import Path

import cv2 as cv

from src.pose.estimator import PoseEstimator
from src.analysis.joint_analyzer import JointAnalyzer
from src.analysis.velocity import VelocityTracker
from src.analysis.frame_data import FrameData
from src.export.csv_exporter import CSVExporter
from src.config.settings import Settings


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Extract pose data from climbing videos.'
    )
    parser.add_argument(
        'video_path',
        type=str,
        help='Path to input video file'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Path to output CSV file (default: data/<video_name>.csv)'
    )
    parser.add_argument(
        '--landmarks', '-l',
        action='store_true',
        help='Include raw landmark positions in output'
    )
    parser.add_argument(
        '--minimal', '-m',
        action='store_true',
        help='Output minimal data (angles + CoM speed only)'
    )
    return parser.parse_args()


def process_video(video_path: str, settings: Settings) -> list[FrameData]:
    """
    Process video and extract frame data.
    
    Args:
        video_path: Path to video file
        settings: Configuration settings
        
    Returns:
        List of FrameData objects, one per frame
    """
    cap = cv.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    fps = cap.get(cv.CAP_PROP_FPS)
    total_frames = int(cap.get(cv.CAP_PROP_FRAME_COUNT))
    
    print(f"Processing video: {video_path}")
    print(f"FPS: {fps}, Total frames: {total_frames}")

    estimator = PoseEstimator(settings)
    analyzer = JointAnalyzer(settings)
    velocity_tracker = VelocityTracker(fps=fps, smoothing_window=3)
    
    frames: list[FrameData] = []
    frame_number = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_ms = (frame_number / fps) * 1000
        
        # Extract pose
        landmarks = estimator.process(frame)
        
        # Calculate angles and velocities
        angles = {}
        velocities = {}
        speeds = {}
        com_velocity = None
        com_speed = 0.0
        
        if landmarks:
            # Joint angles
            angles = analyzer.calculate(landmarks)
            
            # Update velocity tracker
            velocity_tracker.update(landmarks)
            
            # Get velocities and speeds
            velocities = velocity_tracker.get_all_velocities()
            speeds = velocity_tracker.get_all_speeds()
            
            # Center of mass
            com_velocity = velocity_tracker.get_center_of_mass_velocity(landmarks)
            com_speed = velocity_tracker.get_center_of_mass_speed(landmarks)
        
        # Store frame data
        frame_data = FrameData(
            frame_number=frame_number,
            timestamp_ms=timestamp_ms,
            landmarks=landmarks or {},
            angles=angles,
            velocities=velocities,
            speeds=speeds,
            center_of_mass_velocity=com_velocity,
            center_of_mass_speed=com_speed,
        )
        frames.append(frame_data)

        # Progress update
        if frame_number % 100 == 0:
            print(f"Processed frame {frame_number}/{total_frames}")

        frame_number += 1

    cap.release()
    estimator.close()

    print(f"Finished processing {frame_number} frames")
    return frames


def print_summary(frames: list[FrameData]) -> None:
    """Print summary statistics."""
    frames_with_pose = [f for f in frames if f.has_pose()]
    
    if not frames_with_pose:
        print("No poses detected in video.")
        return
    
    print(f"\nSummary:")
    print(f"  Pose detected in {len(frames_with_pose)}/{len(frames)} frames")
    
    # Speed stats
    com_speeds = [f.center_of_mass_speed for f in frames_with_pose]
    if com_speeds:
        avg_speed = sum(com_speeds) / len(com_speeds)
        max_speed = max(com_speeds)
        print(f"  Avg CoM speed: {avg_speed:.1f} px/sec")
        print(f"  Max CoM speed: {max_speed:.1f} px/sec")
    
    # Find fastest hand movement
    max_wrist_speed = 0.0
    max_wrist_frame = 0
    for f in frames_with_pose:
        left_speed = f.get_speed('left_wrist')
        right_speed = f.get_speed('right_wrist')
        wrist_speed = max(left_speed, right_speed)
        if wrist_speed > max_wrist_speed:
            max_wrist_speed = wrist_speed
            max_wrist_frame = f.frame_number
    
    if max_wrist_speed > 0:
        print(f"  Max wrist speed: {max_wrist_speed:.1f} px/sec (frame {max_wrist_frame})")


def main():
    """Main entry point."""
    args = parse_args()
    
    video_path = Path(args.video_path)
    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}")
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path('data') / f"{video_path.stem}.csv"

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    settings = Settings()
    
    # Process video
    frames = process_video(str(video_path), settings)
    
    # Print summary
    print_summary(frames)

    # Export to CSV
    exporter = CSVExporter()
    
    if args.landmarks:
        exporter.export_with_landmarks(frames, output_path)
    elif args.minimal:
        exporter.export_minimal(frames, output_path)
    else:
        exporter.export(frames, output_path)

    print(f"\nExported data to: {output_path}")


if __name__ == '__main__':
    main()
