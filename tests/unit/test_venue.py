import pytest

from talx_to_stac.venue import Venue, VenueError


def test_coordinates_are_written_latitude_first_and_emitted_longitude_first():
    venue = Venue.from_mapping({"Hall": [43.34, 17.81]})
    assert venue.point_for("Hall") == {"type": "Point", "coordinates": [17.81, 43.34]}


@pytest.mark.parametrize("spelling", ["hall", " Hall ", "HALL", "Hall"])
def test_room_names_match_loosely(spelling):
    assert Venue.from_mapping({"Hall": [1.0, 2.0]}).point_for(spelling)["coordinates"] == [2.0, 1.0]


def test_a_room_may_be_keyed_by_its_slug():
    venue = Venue.from_mapping({"245-el11": [1.0, 2.0]})
    assert venue.knows("245-EL11")


def test_an_unknown_room_falls_back_to_the_default_rather_than_failing():
    venue = Venue.from_mapping({"Hall": [1.0, 2.0]}, default=[9.0, 8.0])
    assert venue.point_for("Nowhere")["coordinates"] == [8.0, 9.0]
    assert not venue.knows("Nowhere")


def test_a_venue_that_knows_nothing_still_answers():
    assert Venue.anywhere().point_for("Hall") == {"type": "Point", "coordinates": [0.0, 0.0]}


def test_coordinates_may_be_named():
    venue = Venue.from_mapping({"Hall": {"lat": 1.0, "lon": 2.0}})
    assert venue.point_for("Hall")["coordinates"] == [2.0, 1.0]


@pytest.mark.parametrize("bad", [[91.0, 0.0], [0.0, 181.0], "somewhere", [1.0], None])
def test_a_coordinate_that_is_not_on_earth_is_rejected(bad):
    with pytest.raises(VenueError):
        Venue.from_mapping({"Hall": bad})


def test_a_file_supplies_rooms_and_its_default(tmp_path):
    path = tmp_path / "v.yaml"
    path.write_text("default: [0.0, 0.0]\nHall: [43.0, 17.0]\n", encoding="utf-8")
    venue = Venue.from_file(path)
    assert venue.knows("Hall")
    assert not venue.knows("default")
    assert venue.point_for("Other")["coordinates"] == [0.0, 0.0]
