"""
Export service for combining pose data with labels.
Creates ML-ready CSV files with three-lens labeling schema.
"""
import csv
from pathlib import Path
from .database import Database


class Exporter:
    """Combines raw pose CSV with labels from database."""

    def __init__(self, db: Database):
        self.db = db

    def export_video(self, video_id: int, delete_video: bool = False) -> str:
        """
        Export combined data for a video.

        Args:
            video_id: ID of the video to export
            delete_video: If True, delete the video file after successful export

        Returns path to exported CSV.
        """
        # Get video
        video = self.db.get_video(video_id)
        if not video:
            raise ValueError(f"Video {video_id} not found")

        # Get all moves for this video
        moves = self.db.get_moves_for_video(video_id)

        # Build frame -> label mapping
        frame_labels = {}
        for move in moves:
            # Get environment and outcome for this move
            env = self.db.get_environment_for_move(move.id)
            outcome = self.db.get_outcome_for_move(move.id)
            tags = self.db.get_frame_tags_for_move(move.id)

            for frame in range(move.frame_start, move.frame_end + 1):
                frame_labels[frame] = {
                    'move_id': move.id,
                    # Lens 2: Strategy
                    'approach': move.approach,
                    'size': move.size,
                    'move_tags': '|'.join(move.move_tags) if move.move_tags else '',
                    'timing': move.timing or '',
                    'dyno_style': move.dyno_style or '',
                    'form_quality': move.form_quality,
                    'effort_level': move.effort_level,
                    # Lens 1: Environment
                    'wall_angle': env.wall_angle if env else '',
                    'hold_type_reaching': env.hold_type_reaching if env else '',
                    'hold_type_non_reaching': env.hold_type_non_reaching if env else '',
                    'hold_quality': '|'.join(env.hold_quality) if env and env.hold_quality else '',
                    # Lens 3: Outcome
                    'result': outcome.result if outcome else '',
                    'reach_detail': outcome.reach_detail if outcome else '',
                    'foot_cut': '1' if outcome and outcome.foot_cut else '0' if outcome else '',
                    'confidence': outcome.confidence if outcome else '',
                    # Frame tags (populated below)
                    'frame_tags': [],
                }

            # Add frame tags - collect ALL tags for each frame
            for tag in tags:
                if tag.frame_number in frame_labels:
                    frame_labels[tag.frame_number]['frame_tags'].append({
                        'tag_type': tag.tag_type,
                        'level': tag.level,
                        'locations': tag.locations,
                        'side': tag.side,
                        'traction_source': tag.traction_source,
                        'traction_direction': tag.traction_direction,
                        'note': tag.note,
                    })

        # Read raw CSV
        raw_csv_path = Path(video.csv_path)
        if not raw_csv_path.exists():
            raise ValueError(f"CSV not found: {raw_csv_path}")

        # Create exports directory
        exports_dir = Path('data/exports')
        exports_dir.mkdir(exist_ok=True)

        # Output path
        export_path = exports_dir / f"{raw_csv_path.stem}_labeled.csv"

        # Combine and write
        with open(raw_csv_path, 'r') as infile, open(export_path, 'w', newline='') as outfile:
            reader = csv.DictReader(infile)

            # New fieldnames - three-lens schema
            fieldnames = list(reader.fieldnames) + [
                # Move identification
                'move_id',
                # Lens 2: Strategy
                'approach', 'size', 'move_tags', 'timing', 'dyno_style',
                'form_quality', 'effort_level',
                # Lens 1: Environment
                'wall_angle', 'hold_type_reaching', 'hold_type_non_reaching', 'hold_quality',
                # Lens 3: Outcome
                'result', 'reach_detail', 'foot_cut', 'confidence',
                # Sensation (Frame Tags) - pipe-delimited for multiple tags
                'tag_types', 'tag_levels', 'tag_locations', 'tag_sides',
                'tag_traction_sources', 'tag_traction_directions', 'tag_notes'
            ]

            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                frame_num = int(row.get('frame_number', 0))
                labels = frame_labels.get(frame_num, {})

                # Add move identification
                row['move_id'] = labels.get('move_id', '')

                # Lens 2: Strategy
                row['approach'] = labels.get('approach', '')
                row['size'] = labels.get('size', '')
                row['move_tags'] = labels.get('move_tags', '')
                row['timing'] = labels.get('timing', '')
                row['dyno_style'] = labels.get('dyno_style', '')
                row['form_quality'] = labels.get('form_quality', '')
                row['effort_level'] = labels.get('effort_level', '')

                # Lens 1: Environment
                row['wall_angle'] = labels.get('wall_angle', '')
                row['hold_type_reaching'] = labels.get('hold_type_reaching', '')
                row['hold_type_non_reaching'] = labels.get('hold_type_non_reaching', '')
                row['hold_quality'] = labels.get('hold_quality', '')

                # Lens 3: Outcome
                row['result'] = labels.get('result', '')
                row['reach_detail'] = labels.get('reach_detail', '')
                row['foot_cut'] = labels.get('foot_cut', '')
                row['confidence'] = labels.get('confidence', '')

                # Sensation (Frame Tags) - export ALL tags with pipe-delimited values
                frame_tags = labels.get('frame_tags', [])
                if frame_tags:
                    row['tag_types'] = '|'.join(t['tag_type'] for t in frame_tags)
                    row['tag_levels'] = '|'.join(
                        str(t['level']) if t['level'] is not None else ''
                        for t in frame_tags
                    )
                    row['tag_locations'] = '|'.join(
                        ','.join(t['locations']) if t['locations'] else ''
                        for t in frame_tags
                    )
                    row['tag_sides'] = '|'.join(
                        t['side'] if t['side'] else ''
                        for t in frame_tags
                    )
                    row['tag_traction_sources'] = '|'.join(
                        t['traction_source'] if t['traction_source'] else ''
                        for t in frame_tags
                    )
                    row['tag_traction_directions'] = '|'.join(
                        t['traction_direction'] if t['traction_direction'] else ''
                        for t in frame_tags
                    )
                    row['tag_notes'] = '|'.join(
                        t['note'] if t['note'] else ''
                        for t in frame_tags
                    )
                else:
                    row['tag_types'] = ''
                    row['tag_levels'] = ''
                    row['tag_locations'] = ''
                    row['tag_sides'] = ''
                    row['tag_traction_sources'] = ''
                    row['tag_traction_directions'] = ''
                    row['tag_notes'] = ''

                writer.writerow(row)

        # Delete video file if requested
        if delete_video and video.path:
            video_path = Path(video.path)
            if video_path.exists() and video_path.is_file():
                video_path.unlink()
                print(f"Deleted video file: {video_path}")

        return str(export_path)
