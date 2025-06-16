from django.db.models import Q, Exists, OuterRef, When, IntegerField, FloatField, Count, ExpressionWrapper, Case, Value, F, Prefetch

from fame.models import Fame, FameLevels, FameUsers, ExpertiseAreas
from socialnetwork.models import Posts, SocialNetworkUsers


# general methods independent of html and REST views
# should be used by REST and html views


def _get_social_network_user(user) -> SocialNetworkUsers:
    """Given a FameUser, gets the social network user from the request. Assumes that the user is authenticated."""
    try:
        user = SocialNetworkUsers.objects.get(id=user.id)
    except SocialNetworkUsers.DoesNotExist:
        raise PermissionError("User does not exist")
    return user


def timeline(user: SocialNetworkUsers, start: int = 0, end: int = None, published=True, community_mode=False):
    """Get the timeline of the user. Assumes that the user is authenticated."""

    if community_mode:
        # T4
        # in community mode, posts of communities are displayed if ALL of the following criteria are met:
        # 1. the author of the post is a member of the community
        # 2. the user is a member of the community
        # 3. the post contains the community’s expertise area
        # 4. the post is published or the user is the author

        
        #########################
        # add your code here
        #########################
        user_communities = set(user.communities.all())
        posts = Posts.objects.filter(
            (Q(published=published) | Q(author=user)),
            expertise_area_and_truth_ratings__in=user_communities
        ).distinct().order_by("-submitted")

        filtered_ids = []
        for post in posts:
            post_expertise_areas = set(post.expertise_area_and_truth_ratings.all())
            author_communities = set(post.author.communities.all())
            shared_areas = user_communities & author_communities & post_expertise_areas
            if shared_areas:
                filtered_ids.append(post.id)
        posts = Posts.objects.filter(id__in=filtered_ids).order_by("-submitted")
    else:
        # in standard mode, posts of followed users are displayed
        _follows = user.follows.all()
        posts = Posts.objects.filter(
            (Q(author__in=_follows) & Q(published=published)) | Q(author=user)
        ).order_by("-submitted")
    if end is None:
        return posts[start:]
    else:
        return posts[start:end+1]


def search(keyword: str, start: int = 0, end: int = None, published=True):
    """Search for all posts in the system containing the keyword. Assumes that all posts are public"""
    posts = Posts.objects.filter(
        Q(content__icontains=keyword)
        | Q(author__email__icontains=keyword)
        | Q(author__first_name__icontains=keyword)
        | Q(author__last_name__icontains=keyword),
        published=published,
    ).order_by("-submitted")
    if end is None:
        return posts[start:]
    else:
        return posts[start:end+1]


def follows(user: SocialNetworkUsers, start: int = 0, end: int = None):
    """Get the users followed by this user. Assumes that the user is authenticated."""
    _follows = user.follows.all()
    if end is None:
        return _follows[start:]
    else:
        return _follows[start:end+1]


def followers(user: SocialNetworkUsers, start: int = 0, end: int = None):
    """Get the followers of this user. Assumes that the user is authenticated."""
    _followers = user.followed_by.all()
    if end is None:
        return _followers[start:]
    else:
        return _followers[start:end+1]


def follow(user: SocialNetworkUsers, user_to_follow: SocialNetworkUsers):
    """Follow a user. Assumes that the user is authenticated. If user already follows the user, signal that."""
    if user_to_follow in user.follows.all():
        return {"followed": False}
    user.follows.add(user_to_follow)
    user.save()
    return {"followed": True}


def unfollow(user: SocialNetworkUsers, user_to_unfollow: SocialNetworkUsers):
    """Unfollow a user. Assumes that the user is authenticated. If user does not follow the user anyway, signal that."""
    if user_to_unfollow not in user.follows.all():
        return {"unfollowed": False}
    user.follows.remove(user_to_unfollow)
    user.save()
    return {"unfollowed": True}


def submit_post(
    user: SocialNetworkUsers,
    content: str,
    cites: Posts = None,
    replies_to: Posts = None,
):
    """Submit a post for publication. Assumes that the user is authenticated.
    returns a tuple of three elements:
    1. a dictionary with the keys "published" and "id" (the id of the post)
    2. a list of dictionaries containing the expertise areas and their truth ratings
    3. a boolean indicating whether the user was banned and logged out and should be redirected to the login page
    """

    # create post  instance:
    post = Posts.objects.create(
        content=content,
        author=user,
        cites=cites,
        replies_to=replies_to,
    )

    # classify the content into expertise areas:
    # only publish the post if none of the expertise areas contains bullshit:
    _at_least_one_expertise_area_contains_bullshit, _expertise_areas = (
        post.determine_expertise_areas_and_truth_ratings()
    )
    post.published = (not _at_least_one_expertise_area_contains_bullshit)

    redirect_to_logout = False


    #########################
    # add your code here
    #########################

    for area in _expertise_areas:
        expertise_area = area["expertise_area"]
        if Fame.objects.filter(user=user, expertise_area=expertise_area , fame_level__numeric_value__lt=0).exists():
            post.published = False
        
        truth_rating = area.get("truth_rating")    
        if truth_rating and truth_rating.numeric_value < 0:
            try:
                u = Fame.objects.get(user=user, expertise_area=expertise_area)
                old_fame = u.fame_level
                try:
                    new_level = old_fame.get_next_lower_fame_level()
                    u.fame_level = new_level
                    u.save()
                except ValueError:
                    user.is_active = False
                    user.save()
                    redirect_to_logout = True
                    Posts.objects.filter(author=user).update(published=False)
            except Fame.DoesNotExist:
                confuser_level, _ = FameLevels.objects.get_or_create(name="Confuser", numeric_value=-10)
                Fame.objects.create(user=user, expertise_area=expertise_area, fame_level=confuser_level)
        try:
            fame = Fame.objects.get(user=user, expertise_area=expertise_area)
            super_pro_level = FameLevels.objects.get(name="Super Pro")
            if fame.fame_level.numeric_value < super_pro_level.numeric_value:
                user.communities.remove(expertise_area)
        except (Fame.DoesNotExist, FameLevels.DoesNotExist):
            pass



       
            
            

            

    
        


    post.save()

    return (
        {"published": post.published, "id": post.id},
        _expertise_areas,
        redirect_to_logout,
    )


def rate_post(
    user: SocialNetworkUsers, post: Posts, rating_type: str, rating_score: int
):
    """Rate a post. Assumes that the user is authenticated. If user already rated the post with the given rating_type,
    update that rating score."""
    user_rating = None
    try:
        user_rating = user.userratings_set.get(post=post, rating_type=rating_type)
    except user.userratings_set.model.DoesNotExist:
        pass

    if user == post.author:
        raise PermissionError(
            "User is the author of the post. You cannot rate your own post."
        )

    if user_rating is not None:
        # update the existing rating:
        user_rating.rating_score = rating_score
        user_rating.save()
        return {"rated": True, "type": "update"}
    else:
        # create a new rating:
        user.userratings_set.add(
            post,
            through_defaults={"rating_type": rating_type, "rating_score": rating_score},
        )
        user.save()
        return {"rated": True, "type": "new"}


def fame(user: SocialNetworkUsers):
    """Get the fame of a user. Assumes that the user is authenticated."""
    try:
        user = SocialNetworkUsers.objects.get(id=user.id)
    except SocialNetworkUsers.DoesNotExist:
        raise ValueError("User does not exist")

    return user, Fame.objects.filter(user=user)


def bullshitters():
    """Return a Python dictionary mapping each existing expertise area in the fame profiles to a list of the users
    having negative fame for that expertise area. Each list should contain Python dictionaries as entries with keys
    ``user'' (for the user) and ``fame_level_numeric'' (for the corresponding fame value), and should be ranked, i.e.,
    users with the lowest fame are shown first, in case there is a tie, within that tie sort by date_joined
    (most recent first). Note that expertise areas with no expert may be omitted.
    """
    
    #########################
    # add your code here
    #########################
    result = {}
    for area in ExpertiseAreas.objects.all():
        users = area.fame_set.filter(
            fame_level__numeric_value__lt=0
        ).order_by("fame_level__numeric_value", "-user__date_joined")
        if users.exists():
            result[area] = [
                {"user": u.user, "fame_level_numeric": u.fame_level.numeric_value}
                for u in users
            ]
    return result


def join_community(user: SocialNetworkUsers, community: ExpertiseAreas):
    """Join a specified community. Note that this method does not check whether the user is eligible for joining the
    community.
    """
    
    #########################
    # add your code here
    #########################
   
    if community in user.communities.all():
        return {"joined": False}
    user.communities.add(community)
    user.save()
    return {"joined": True}



def leave_community(user: SocialNetworkUsers, community: ExpertiseAreas):
    """Leave a specified community."""
   
    if community not in user.communities.all():
        return {"left": False}
    user.communities.remove(community)
    user.save()
    return {"left": True}



def similar_users(user: SocialNetworkUsers):
    """Compute the similarity of user with all other users. The method returns a QuerySet of FameUsers annotated
    with an additional field 'similarity'. Sort the result in descending order according to 'similarity', in case
    there is a tie, within that tie sort by date_joined (most recent first)"""
    pass
    #########################
    # add your code here
    #########################

