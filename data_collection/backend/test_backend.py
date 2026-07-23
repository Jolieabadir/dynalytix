"""
Simple test to verify backend components work independently.
Tests the three-lens labeling schema: Environment / Strategy / Outcome

Run with: python test_backend.py
"""
from pathlib import Path
from datetime import datetime

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from labeling.models import (
    Video, Move, Environment, Outcome, FrameTag,
    APPROACHES, SIZES, MOVE_TAGS,
    WALL_ANGLES, HOLD_TYPES, HOLD_QUALITIES,
    RESULTS, REACH_DETAILS, CONFIDENCE_LEVELS,
    TAG_TYPES, BODY_PARTS, SIDES, TRACTION_SOURCES
)
from labeling.database import Database


def test_models():
    """Test that models work correctly."""
    print("Testing models...")

    # Test Video
    video = Video(
        id=1,
        filename="test.mov",
        path="videos/test.mov",
        csv_path="data/test.csv",
        fps=30.0,
        total_frames=900,
        duration_ms=30000.0,
        uploaded_at=datetime.now()
    )

    video_dict = video.to_dict()
    assert video_dict['filename'] == "test.mov"
    assert video_dict['fps'] == 30.0
    print("✓ Video model works")

    # Test Move (Lens 2: Strategy)
    move = Move(
        id=1,
        video_id=1,
        frame_start=150,
        frame_end=200,
        timestamp_start_ms=5000.0,
        timestamp_end_ms=6666.7,
        approach='dynamic',
        size='large',
        move_tags=['heel_hook', 'balance'],
        form_quality=4,
        effort_level=7,
        contextual_data={},
        tags=['tweaky_feeling'],
        description="Test move",
        labeled_at=datetime.now()
    )

    assert abs(move.duration_seconds() - 1.6667) < 0.001
    assert move.frame_count() == 51
    print("✓ Move model works")

    # Test Environment (Lens 1)
    env = Environment(
        id=1,
        move_id=1,
        wall_angle='steep',
        hold_type_reaching='gaston',
        hold_type_non_reaching='horizontal_edge',
        hold_quality=['sloped', 'small']
    )

    env_dict = env.to_dict()
    assert env_dict['wall_angle'] == 'steep'
    assert 'sloped' in env_dict['hold_quality']
    print("✓ Environment model works")

    # Test Outcome (Lens 3)
    outcome = Outcome(
        id=1,
        move_id=1,
        result='success',
        reach_detail='reached_controlled',
        foot_cut=False,
        confidence='high'
    )

    outcome_dict = outcome.to_dict()
    assert outcome_dict['result'] == 'success'
    assert outcome_dict['foot_cut'] == False
    print("✓ Outcome model works")

    # Test FrameTag (Sensation)
    tag = FrameTag(
        id=1,
        move_id=1,
        frame_number=155,
        timestamp_ms=5166.7,
        tag_type='sharp_pain',
        level=6,
        locations=['left_knee'],
        side='left',
        traction_source='hip',
        traction_direction='internal rotation',
        note="Sharp pain during heel hook",
        tagged_at=datetime.now()
    )

    assert tag.is_sensation_tag() == True
    assert tag.side == 'left'
    assert tag.traction_source == 'hip'
    print("✓ FrameTag model works")

    # Test taxonomy constants
    assert 'static' in APPROACHES
    assert 'dynamic' in APPROACHES
    assert 'coordination' in APPROACHES
    print("✓ APPROACHES loaded")

    assert 'small' in SIZES
    assert 'medium' in SIZES
    assert 'large' in SIZES
    print("✓ SIZES loaded")

    assert 'heel_hook' in MOVE_TAGS
    assert 'toe_hook' in MOVE_TAGS
    print("✓ MOVE_TAGS loaded")

    assert 'steep' in WALL_ANGLES
    assert 'vertical' in WALL_ANGLES
    print("✓ WALL_ANGLES loaded")

    assert 'gaston' in HOLD_TYPES
    assert 'horizontal_edge' in HOLD_TYPES
    print("✓ HOLD_TYPES loaded")

    assert 'sloped' in HOLD_QUALITIES
    assert 'incut' in HOLD_QUALITIES
    print("✓ HOLD_QUALITIES loaded")

    assert 'success' in RESULTS
    assert 'fall' in RESULTS
    print("✓ RESULTS loaded")

    assert 'sharp_pain' in TAG_TYPES
    assert 'audible_pop' in TAG_TYPES
    print("✓ TAG_TYPES loaded")

    assert 'left' in SIDES
    assert 'hip' in TRACTION_SOURCES
    print("✓ SIDES and TRACTION_SOURCES loaded")

    print("\n✅ All model tests passed!\n")


def test_database():
    """Test that database operations work."""
    print("Testing database...")

    # Use test database
    db = Database('data/test_labels.db')
    db.init()
    print("✓ Database initialized")

    # Test Video CRUD
    video = Video(
        filename="test.mov",
        path="videos/test.mov",
        csv_path="data/test.csv",
        fps=30.0,
        total_frames=900,
        duration_ms=30000.0,
        uploaded_at=datetime.now()
    )

    video_id = db.create_video(video)
    assert video_id > 0
    print(f"✓ Created video with ID: {video_id}")

    retrieved_video = db.get_video(video_id)
    assert retrieved_video.filename == "test.mov"
    print("✓ Retrieved video")

    all_videos = db.get_all_videos()
    assert len(all_videos) >= 1
    print(f"✓ Listed {len(all_videos)} video(s)")

    # Test Move CRUD (Lens 2: Strategy)
    move = Move(
        video_id=video_id,
        frame_start=150,
        frame_end=200,
        timestamp_start_ms=5000.0,
        timestamp_end_ms=6666.7,
        approach='dynamic',
        size='large',
        move_tags=['heel_hook', 'balance'],
        form_quality=4,
        effort_level=7,
        contextual_data={},
        tags=['tweaky_feeling'],
        description="Test move",
        labeled_at=datetime.now()
    )

    move_id = db.create_move(move)
    assert move_id > 0
    print(f"✓ Created move with ID: {move_id}")

    retrieved_move = db.get_move(move_id)
    assert retrieved_move.approach == 'dynamic'
    assert retrieved_move.size == 'large'
    assert 'heel_hook' in retrieved_move.move_tags
    assert 'balance' in retrieved_move.move_tags
    print("✓ Retrieved move with strategy data")

    moves = db.get_moves_for_video(video_id)
    assert len(moves) == 1
    print(f"✓ Listed {len(moves)} move(s) for video")

    # Test update
    move.description = "Updated description"
    move.id = move_id
    db.update_move(move)
    updated_move = db.get_move(move_id)
    assert updated_move.description == "Updated description"
    print("✓ Updated move")

    # Test Environment CRUD (Lens 1)
    env = Environment(
        move_id=move_id,
        wall_angle='steep',
        hold_type_reaching='gaston',
        hold_type_non_reaching='horizontal_edge',
        hold_quality=['sloped', 'small']
    )

    env_id = db.create_environment(env)
    assert env_id > 0
    print(f"✓ Created environment with ID: {env_id}")

    retrieved_env = db.get_environment_for_move(move_id)
    assert retrieved_env.wall_angle == 'steep'
    assert retrieved_env.hold_type_reaching == 'gaston'
    assert 'sloped' in retrieved_env.hold_quality
    print("✓ Retrieved environment")

    # Update environment
    env.id = env_id
    env.wall_angle = 'vertical'
    db.update_environment(env)
    updated_env = db.get_environment(env_id)
    assert updated_env.wall_angle == 'vertical'
    print("✓ Updated environment")

    # Test Outcome CRUD (Lens 3)
    outcome = Outcome(
        move_id=move_id,
        result='success',
        reach_detail='reached_controlled',
        foot_cut=False,
        confidence='high'
    )

    outcome_id = db.create_outcome(outcome)
    assert outcome_id > 0
    print(f"✓ Created outcome with ID: {outcome_id}")

    retrieved_outcome = db.get_outcome_for_move(move_id)
    assert retrieved_outcome.result == 'success'
    assert retrieved_outcome.reach_detail == 'reached_controlled'
    assert retrieved_outcome.foot_cut == False
    print("✓ Retrieved outcome")

    # Update outcome
    outcome.id = outcome_id
    outcome.foot_cut = True
    db.update_outcome(outcome)
    updated_outcome = db.get_outcome(outcome_id)
    assert updated_outcome.foot_cut == True
    print("✓ Updated outcome")

    # Test FrameTag CRUD with new fields
    tag = FrameTag(
        move_id=move_id,
        frame_number=155,
        timestamp_ms=5166.7,
        tag_type='sharp_pain',
        level=6,
        locations=['left_knee'],
        side='left',
        traction_source='hip',
        traction_direction='internal rotation',
        note="Sharp pain during heel hook",
        tagged_at=datetime.now()
    )

    tag_id = db.create_frame_tag(tag)
    assert tag_id > 0
    print(f"✓ Created frame tag with ID: {tag_id}")

    retrieved_tag = db.get_frame_tag(tag_id)
    assert retrieved_tag.tag_type == 'sharp_pain'
    assert retrieved_tag.level == 6
    assert 'left_knee' in retrieved_tag.locations
    assert retrieved_tag.side == 'left'
    assert retrieved_tag.traction_source == 'hip'
    assert retrieved_tag.traction_direction == 'internal rotation'
    print("✓ Retrieved frame tag with new fields")

    # Test multiple tags on same frame (for multi-tag export test)
    tag2 = FrameTag(
        move_id=move_id,
        frame_number=155,  # Same frame as tag1
        timestamp_ms=5166.7,
        tag_type='unstable',
        level=4,
        locations=['left_hip'],
        side='left',
        traction_source=None,
        traction_direction=None,
        note="Felt unstable",
        tagged_at=datetime.now()
    )

    tag2_id = db.create_frame_tag(tag2)
    assert tag2_id > 0
    print(f"✓ Created second frame tag on same frame with ID: {tag2_id}")

    tags = db.get_frame_tags_for_move(move_id)
    assert len(tags) == 2
    print(f"✓ Listed {len(tags)} tags for move (multi-tag scenario)")

    # Test delete frame tags
    db.delete_frame_tag(tag_id)
    db.delete_frame_tag(tag2_id)
    assert db.get_frame_tag(tag_id) is None
    assert db.get_frame_tag(tag2_id) is None
    print("✓ Deleted frame tags")

    # Test cascade delete (move should delete environment and outcome too)
    db.delete_move(move_id)
    assert db.get_move(move_id) is None
    assert db.get_environment_for_move(move_id) is None
    assert db.get_outcome_for_move(move_id) is None
    print("✓ Deleted move (cascade to environment and outcome)")

    print("\n✅ All database tests passed!\n")

    # Clean up test database
    Path('data/test_labels.db').unlink(missing_ok=True)
    print("✓ Cleaned up test database")


def test_exporter():
    """Test the exporter with multi-tag support."""
    print("Testing exporter...")

    from labeling.exporter import Exporter
    import csv

    # Create test database with data
    db = Database('data/test_export_labels.db')
    db.init()

    # Create a video
    video = Video(
        filename="export_test.mov",
        path="",
        csv_path="data/test_pose.csv",
        fps=30.0,
        total_frames=10,
        duration_ms=333.3,
        uploaded_at=datetime.now()
    )
    video_id = db.create_video(video)

    # Create minimal pose CSV
    pose_csv_path = Path('data/test_pose.csv')
    pose_csv_path.parent.mkdir(exist_ok=True)
    with open(pose_csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['frame_number', 'timestamp_ms', 'nose_x', 'nose_y'])
        writer.writeheader()
        for i in range(10):
            writer.writerow({
                'frame_number': i,
                'timestamp_ms': i * 33.3,
                'nose_x': 0.5,
                'nose_y': 0.5
            })

    # Create a move
    move = Move(
        video_id=video_id,
        frame_start=2,
        frame_end=7,
        timestamp_start_ms=66.6,
        timestamp_end_ms=233.1,
        approach='static',
        size='small',
        move_tags=['balance'],
        form_quality=3,
        effort_level=5,
        contextual_data={},
        tags=[],
        description="",
        labeled_at=datetime.now()
    )
    move_id = db.create_move(move)

    # Create environment
    env = Environment(
        move_id=move_id,
        wall_angle='vertical',
        hold_type_reaching='horizontal_edge',
        hold_type_non_reaching='side_pull',
        hold_quality=['incut']
    )
    db.create_environment(env)

    # Create outcome
    outcome = Outcome(
        move_id=move_id,
        result='success',
        reach_detail='reached_controlled',
        foot_cut=False,
        confidence='med'
    )
    db.create_outcome(outcome)

    # Create MULTIPLE frame tags on same frame (test multi-tag export)
    tag1 = FrameTag(
        move_id=move_id,
        frame_number=4,
        timestamp_ms=133.2,
        tag_type='sharp_pain',
        level=5,
        locations=['left_shoulder'],
        side='left',
        traction_source='hand',
        traction_direction='lateral',
        note="Sharp pain",
        tagged_at=datetime.now()
    )
    db.create_frame_tag(tag1)

    tag2 = FrameTag(
        move_id=move_id,
        frame_number=4,  # Same frame!
        timestamp_ms=133.2,
        tag_type='unstable',
        level=3,
        locations=['left_hip', 'core'],
        side='left',
        traction_source='hip',
        traction_direction='rotation',
        note="Felt wobbly",
        tagged_at=datetime.now()
    )
    db.create_frame_tag(tag2)

    # Export
    exporter = Exporter(db)
    export_path = exporter.export_video(video_id)
    print(f"✓ Exported to: {export_path}")

    # Verify export contains correct columns and multi-tag data
    with open(export_path, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

        # Check new columns exist
        assert 'approach' in reader.fieldnames
        assert 'size' in reader.fieldnames
        assert 'move_tags' in reader.fieldnames
        assert 'wall_angle' in reader.fieldnames
        assert 'hold_type_reaching' in reader.fieldnames
        assert 'result' in reader.fieldnames
        assert 'reach_detail' in reader.fieldnames
        assert 'foot_cut' in reader.fieldnames
        assert 'confidence' in reader.fieldnames
        assert 'tag_types' in reader.fieldnames
        assert 'tag_sides' in reader.fieldnames
        assert 'tag_traction_sources' in reader.fieldnames
        print("✓ All three-lens columns present in export")

        # Find frame 4 (with two tags)
        frame4 = next(r for r in rows if int(r['frame_number']) == 4)

        # Verify multi-tag export (pipe-delimited)
        assert '|' in frame4['tag_types'], "Multi-tag should use pipe delimiter"
        assert 'sharp_pain' in frame4['tag_types']
        assert 'unstable' in frame4['tag_types']
        print("✓ Multi-tag export works (pipe-delimited)")

        # Verify environment data
        assert frame4['wall_angle'] == 'vertical'
        assert frame4['hold_type_reaching'] == 'horizontal_edge'
        print("✓ Environment data exported")

        # Verify outcome data
        assert frame4['result'] == 'success'
        assert frame4['reach_detail'] == 'reached_controlled'
        print("✓ Outcome data exported")

        # Verify strategy data
        assert frame4['approach'] == 'static'
        assert frame4['size'] == 'small'
        print("✓ Strategy data exported")

    print("\n✅ All exporter tests passed!\n")

    # Clean up
    Path('data/test_export_labels.db').unlink(missing_ok=True)
    Path('data/test_pose.csv').unlink(missing_ok=True)
    Path(export_path).unlink(missing_ok=True)
    print("✓ Cleaned up test files")


if __name__ == '__main__':
    print("=" * 60)
    print("BACKEND COMPONENT TESTS (Three-Lens Schema)")
    print("=" * 60)
    print()

    test_models()
    test_database()
    test_exporter()

    print("=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    print("\nBackend is ready. You can now:")
    print("1. Run the API: uvicorn src.web.api:app --reload")
    print("2. Visit: http://localhost:8000/docs for API documentation")
    print()
