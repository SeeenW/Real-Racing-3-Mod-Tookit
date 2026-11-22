

//%feature FOG
//%feature SUN_FOG
//%feature NIGHT
//%feature GLOW
//%feature NIGHT_GLOW
//%feature REFLECTOR
//%feature REFLECTOR_MARKER
//%feature PLANAR_REFLECTION
//%feature FLAT_COLOUR
//%feature SCATTERED_TRANSLUCENCY
//%feature DETAIL
//%feature DETAIL_ROAD
//%feature ALBEDO_SCALE
//%feature ALBEDO_DETAIL
//%feature NORMAL_MAP
//%feature WORLD_NORMAL_MAP
//%feature WORLD_NORMAL_MAP_UNIQUE
//%feature NORMAL_SCALE
//%feature GLOSS_MAP
//%feature WORLD_GLOSS_MAP
//%feature GLOSS_DETAIL
//%feature METALLIC_MAP
//%feature SPECULAR_MAP
//%feature SHADOW_MAP
//%feature VERTEX_WET
//%feature WIND_TREE_DEFORM
//%feature WIND_FLAG_DEFORM
//%feature DIFFUSE_LIGHTING
//%feature SPECULAR_LIGHTING
//%feature DIRECT_LIGHTING
//%feature AMBIENT_LIGHTING
//%feature ALPHA_TEST
//%feature CACHED_SHADOW_MAP
//%feature UPDATE_CACHED_SHADOW_MAP
//%feature VERTEX_COLOUR
//%feature PARTICLE_SHADOW
//%feature RENDER_TO_CUBEMAP
//%feature SUPPORT_INSTANCING
//%feature CUBE_AMBIENT
//%feature SEPARATE_ALPHA
//%feature VERTEX_ALPHA
//%feature ALBEDO_TO_NORMAL
//%feature ANTIALIASED_LINES

//%feature HDR_ENCODE
//%debugfeature HDR_LINEAR
//%debugfeature HDR_ENCODED_ENV
//%debugfeature HDR_LINEAR_ENV
//%precompile SUN_FOG, DETAIL, WORLD_NORMAL_MAP_UNIQUE
//%precompile DETAIL, RENDER_TO_CUBEMAP, WORLD_NORMAL_MAP_UNIQUE, -FOG

#define DIFFUSE_LIGHTING
#define SPECULAR_LIGHTING
#define DIRECT_LIGHTING
#define AMBIENT_LIGHTING

//%include utility.xsh
//%include pbr_utility.xsh

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec2 a_TexCoord0;	//%attributeID MT_UV_0

#if defined(SHADOW_MAP) && !defined(CACHED_SHADOW_MAP)
attribute highp vec2 a_TexCoord1; //%attributeID MT_UV_1

	#if defined(SUPPORT_INSTANCING)
		attribute(MT_LIGHTMAP_SCALE_BIAS) highp vec4 u_LightmapScaleBias;
	#endif
#endif

#if defined(SEPARATE_ALPHA) || defined(ALBEDO_TO_NORMAL)
	attribute highp vec2 a_TexCoord2; //%attributeID MT_UV_0
	varying highp vec2 v_TexCoord2;
#endif

attribute highp vec3 a_Normal; //%attributeID MT_NORMAL

#if defined(NORMAL_MAP)
attribute highp vec3 a_Tangent; //%attributeID MT_TANGENT
attribute highp vec3 a_Bitangent; //%attributeID MT_BITANGENT
varying highp vec3 v_Tangent_W;
varying highp vec3 v_Bitangent_W;
#endif

uniform highp vec3 u_CamPos;
uniform highp vec3 u_LightDirWorldSpace;

#if defined(SUPPORT_INSTANCING)
	attribute(MT_MODEL_TO_WORLD) highp mat4 u_ModelToWorld;
#else
	uniform highp mat4 u_ModelToWorld;
#endif

#if defined(SUPPORT_INSTANCING)
	uniform highp mat4 u_WorldToProj;
#else
	uniform highp mat4 u_ModelToProj;

	#if defined(ANTIALIASED_LINES)
	uniform highp mat4 u_WorldToProj;
	#endif
#endif

varying highp vec3 v_Pos_W;
varying highp vec3 v_Normal_W;

varying highp vec2 v_TexCoord0;
varying highp vec2 v_TexCoord1;

#if defined(WIND_TREE_DEFORM) || defined(WIND_FLAG_DEFORM) || defined(VERTEX_WET) || defined(VERTEX_COLOUR) || defined(VERTEX_ALPHA)
	attribute lowp vec4 a_Colour;		//%attributeID MT_COLOUR
#endif

#if defined(VERTEX_WET) || defined(VERTEX_COLOUR)  || defined(VERTEX_ALPHA) 
	varying lowp vec4 v_VertexColour;
#endif

#if defined (ANTIALIASED_LINES)
	varying lowp float v_aaLineTransparency;
#endif

#if defined(WIND_TREE_DEFORM) || defined(WIND_FLAG_DEFORM)
	uniform highp float u_Time;					
#endif

#if defined(WIND_FLAG_DEFORM) && defined(SUPPORT_INSTANCING)
	attribute(MT_BBOX_SIZE) highp vec4 u_BBoxSize;
#endif

#ifdef WORLD_GLOSS_MAP
	uniform mediump float mu_WorldGlossScale;
	varying highp vec2 v_WorldGlossMapCoord;
#endif

#ifdef DETAIL
	uniform mediump float mu_DetailFreq;
	varying highp vec2 v_DetailMapCoord;
	uniform mediump float u_detailTextureOffset;
#endif

#ifdef DETAIL_ROAD
	uniform mediump float mu_DetailFreqRoad;
	varying highp vec2 v_DetailMapCoord;
	uniform mediump float u_detailTextureOffset;
#endif

#ifdef FOG
	#ifdef SUN_FOG
		uniform highp vec3 u_FogParams; // (start, factor, saturation)
		uniform lowp vec3 u_FogColour;
		uniform highp vec3 u_FogSunParams; // (start, factor, saturation)
		uniform lowp vec3 u_FogSunColour;
		uniform highp float u_FogSunPower;

		varying lowp float v_FogFactor;
		varying lowp vec3 v_FogColour;
	#else
		uniform highp vec3 u_FogParams; // (start, factor, saturation)
		varying lowp float v_FogFactor;
	#endif
#endif

#if defined(NIGHT)
	uniform highp mat4 u_HeadLightMatrix;
	varying highp vec3 v_PosHeadLightSpace;
#endif

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

const highp float c_zero = 0.0;
const highp float c_one = 1.0;

void main()
{
	// Position and normal
	highp vec3 inPos = a_Position;
	highp vec3 inNormal = a_Normal;

	

	#if defined (WIND_TREE_DEFORM)
		inPos += treeDeformOffset( a_Position, u_ModelToWorld[3].xyz, a_Colour.rgb, inNormal );
	#endif

	#if defined(WIND_FLAG_DEFORM)
		#if defined(SUPPORT_INSTANCING)
				highp vec3 bboxSize = max(vec3(1.0), u_BBoxSize.xyz);
		#else
				highp vec3 bboxSize = vec3(1.0);
		#endif
		inPos += flagDeformOffset( bboxSize, a_Position, u_ModelToWorld[3].xyz, a_Colour.rgb, inNormal );
	#endif


	v_Normal_W = (u_ModelToWorld * vec4(inNormal, c_zero)).xyz;
	v_Pos_W = (u_ModelToWorld * vec4(inPos, c_one)).xyz;

#if defined(SUPPORT_INSTANCING)
	highp vec4 pos = u_WorldToProj * vec4( v_Pos_W, c_one );
#else
	#if defined (ANTIALIASED_LINES) && !defined(SUPPORT_INSTANCING)
		highp float wCoord = dot( vec4( inPos, c_one), vec4(u_ModelToProj[0].w , u_ModelToProj[1].w, u_ModelToProj[2].w, u_ModelToProj[3].w) );
		v_Pos_W += AntialisedLines(normalize(v_Normal_W), wCoord, v_aaLineTransparency);
		highp vec4 pos = u_WorldToProj * vec4( v_Pos_W, c_one );
	#else
		highp vec4 pos = u_ModelToProj * vec4( inPos, c_one);
	#endif
#endif

#if defined(NORMAL_MAP)
	v_Tangent_W = normalize((u_ModelToWorld * vec4(a_Tangent, c_zero)).xyz);
	v_Bitangent_W = normalize((u_ModelToWorld * vec4(a_Bitangent, c_zero)).xyz);
#endif

	v_TexCoord0 = a_TexCoord0 * uvMult;

#if defined(SHADOW_MAP) && !defined(CACHED_SHADOW_MAP)
	v_TexCoord1 = a_TexCoord1 * uvMult;

	#if defined(SUPPORT_INSTANCING)
		v_TexCoord1 = v_TexCoord1 * u_LightmapScaleBias.xy + u_LightmapScaleBias.zw;
	#endif
#endif

#if defined(SEPARATE_ALPHA) || defined(ALBEDO_TO_NORMAL)
	v_TexCoord2 = a_TexCoord2 * uvMult;
#endif

#ifdef WORLD_GLOSS_MAP
	v_WorldGlossMapCoord = a_Position.xz / mu_WorldGlossScale;
#endif

#ifdef DETAIL
	// Detail map for other surfaces
	calcDetailMapCoordVec( v_Pos_W, u_CamPos, mu_DetailFreq, v_DetailMapCoord );
	//v_DetailMapCoord += vec2( u_detailTextureOffset );
#endif

#ifdef DETAIL_ROAD
	// Detail map
	calcDetailMapCoordVec( v_Pos_W, u_CamPos, mu_DetailFreqRoad, v_DetailMapCoord );
	//v_DetailMapCoord += vec2( u_detailTextureOffset );
#endif

#ifdef FOG
	#ifdef SUN_FOG
		highp vec3 vertexToEyeWorldSpace = normalize(u_CamPos - v_Pos_W);

		// Calculate sun fog contribution
		float sunFogFactor = clamp(dot(u_LightDirWorldSpace, vertexToEyeWorldSpace), 0.0, 1.0);
		sunFogFactor = pow(sunFogFactor, u_FogSunPower);
		
		// Lerp between ambient and sun fog
		vec3 fogParams = mix(u_FogParams, u_FogSunParams, sunFogFactor);
		v_FogColour = mix(u_FogColour, u_FogSunColour, sunFogFactor);

		// Increase with distance up to max saturation
		v_FogFactor = clamp( (pos.w - fogParams.x) * fogParams.y, c_zero, fogParams.z );
	#else
		v_FogFactor = clamp( (pos.w - u_FogParams.x) * u_FogParams.y, c_zero, u_FogParams.z );
	#endif
#endif

#if defined(VERTEX_WET) || defined(VERTEX_COLOUR) || defined(VERTEX_ALPHA)
	v_VertexColour = a_Colour;
#endif

#if defined(NIGHT)
	v_PosHeadLightSpace = (u_HeadLightMatrix * vec4(a_Position, 1.0)).xyz;
#endif

	gl_Position = pos;
}
