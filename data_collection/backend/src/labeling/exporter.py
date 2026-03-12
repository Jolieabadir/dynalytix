"""
Export service for combining pose data with labels.
Creates ML-ready CSV files.
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
        
        # Get all moves and frame tags for this video
        moves = self.db.get_moves_for_video(video_id)
        
        # Build frame -> label mapping
        frame_labels = {}
        for move in moves:
            tags = self.db.get_frame_tags_for_move(move.id)
            for frame in range(move.frame_start, move.frame_end + 1):
                frame_labels[frame] = {
                    'move_id': move.id,
                    'move_type': move.move_type,
                    'form_quality': move.form_quality,
                    'effort_level': move.effort_level,
                    'technique_modifiers': ','.join(move.technique_modifiers) if move.technique_modifiers else '',
                    'tags': [],
                }
            # Add frame tags
            for tag in tags:
                if tag.frame_number in frame_labels:
                    frame_labels[tag.frame_number]['tags'].append({
                        'tag_type': tag.tag_type,
                        'level': tag.level,
                        'locations': tag.locations,
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
            
            # New fieldnames - added technique_modifiers
            fieldnames = list(reader.fieldnames) + [
                'move_id', 'move_type', 'form_quality', 'effort_level', 'technique_modifiers',
                'tag_type', 'tag_level', 'tag_locations', 'tag_note'
            ]
            
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in reader:
                frame_num = int(row.get('frame_number', 0))
                labels = frame_labels.get(frame_num, {})
                
                # Add label columns
                row['move_id'] = labels.get('move_id', '')
                row['move_type'] = labels.get('move_type', '')
                row['form_quality'] = labels.get('form_quality', '')
                row['effort_level'] = labels.get('effort_level', '')
                row['technique_modifiers'] = labels.get('technique_modifiers', '')
                
                # Add first tag (if any)
                tags = labels.get('tags', [])
                if tags:
                    row['tag_type'] = tags[0]['tag_type']
                    row['tag_level'] = tags[0]['level']
                    row['tag_locations'] = ','.join(tags[0]['locations'])
                    row['tag_note'] = tags[0]['note']
                else:
                    row['tag_type'] = ''
                    row['tag_level'] = ''
                    row['tag_locations'] = ''
                    row['tag_note'] = ''
                
                writer.writerow(row)
        
        # Delete video file if requested
        if delete_video and video.path:
            video_path = Path(video.path)
            if video_path.exists() and video_path.is_file():
                video_path.unlink()
                print(f"Deleted video file: {video_path}")
        
        return str(export_path)
